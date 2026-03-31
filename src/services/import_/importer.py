"""
知识导入服务
负责知识文件的导入、管理和统计
支持并行处理和批量向量计算
集成流式读取、长度分桶、动态批处理等优化
"""

import asyncio
import logging
import time
import torch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from src.config import settings
from src.models.knowledge import (
    KnowledgeImportResult,
    KnowledgeType,
    get_knowledge_type_by_path,
    get_knowledge_type_config,
    VectorFieldType,
)
from src.services.import_.models import (
    ImportStatus,
    ManageAction,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
    KnowledgeManageRequest,
    KnowledgeManageResponse,
    KnowledgeStatistics,
    ImportResult,
)
from src.services.embedding import embedding_service
from src.services.vector import vector_compute_service, VectorData
from src.services.vector.batch_optimizer import (
    batch_optimizer,
    BucketType,
    TokenInfo,
    BatchGroup,
)
from src.services.vector.chunker import (
    streaming_processor,
    memory_efficient_chunker,
)
from src.services.vector.multiprocess import (
    parallel_processor,
    multi_process_encoder,
)
from src.utils.gpu_memory import get_gpu_info, clear_gpu_cache, get_optimal_batch_size

logger = logging.getLogger(__name__)

_gpu_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gpu_worker")


class KnowledgeImporter:
    """知识导入服务 - 支持并行处理和批量向量计算"""
    
    def __init__(self) -> None:
        self._initialized = False
    
    async def initialize(self) -> None:
        logger.info("开始初始化知识导入服务...")
        
        if settings.enable_embedding:
            await embedding_service.initialize()
        
        if embedding_service.is_available:
            await vector_compute_service.initialize()
            self._initialized = True
            
            model_info = embedding_service.get_model_info()
            if model_info.get("model_name"):
                multi_process_encoder.set_model(
                    model_info["model_name"],
                    embedding_service.device
                )
        
        logger.info("知识导入服务初始化完成")
    
    def switch_embedding_model(self, model_key: str) -> dict[str, Any]:
        return embedding_service.switch_model(model_key)
    
    def get_current_model_info(self) -> dict[str, Any]:
        return embedding_service.get_model_info()
    
    def _get_vector_data(self, file_path: Path) -> Optional[tuple[KnowledgeType, VectorData]]:
        knowledge_type = get_knowledge_type_by_path(str(file_path))
        if not knowledge_type:
            return None
        
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            return None
        
        vector_data = None
        
        if config.vector_field == VectorFieldType.FILE_NAME:
            form_name = file_path.stem
            vector_data = VectorData(
                doc_id=form_name,
                doc_title=form_name,
                doc_path=str(file_path),
                doc_summary=form_name,
                content_for_embedding=form_name,
            )
        
        elif config.vector_field == VectorFieldType.SUMMARY:
            vector_data = vector_compute_service.get_vector_data_for_file(str(file_path))
        
        if vector_data:
            return (knowledge_type, vector_data)
        return None
    
    def _encode_batch_sync(self, texts: list[str], batch_size: int) -> list:
        model = embedding_service.model
        if not model:
            return [None] * len(texts)
        
        model_type = embedding_service.model_type
        
        if model_type == "gguf":
            return self._encode_batch_gguf(texts)
        
        device = embedding_service.device
        
        all_embeddings = [None] * len(texts)
        total_items = len(texts)
        
        if device == "cuda":
            all_embeddings = self._encode_batch_cuda_pipeline(texts, batch_size)
        else:
            with torch.no_grad():
                for batch_idx in range(0, total_items, batch_size):
                    end_idx = min(batch_idx + batch_size, total_items)
                    batch = texts[batch_idx:end_idx]
                    
                    features = model.tokenize(batch)
                    features = {k: v.to(device) for k, v in features.items()}
                    
                    output = model(features)
                    embeddings = output['sentence_embedding']
                    
                    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
                    
                    all_embeddings[batch_idx:end_idx] = embeddings.cpu().tolist()
        
        return all_embeddings
    
    def _encode_batch_cuda_pipeline(self, texts: list[str], batch_size: int) -> list:
        """CUDA流水线处理：数据传输与计算重叠"""
        model = embedding_service.model
        device = embedding_service.device
        total_items = len(texts)
        all_embeddings = [None] * total_items
        
        stream_compute = torch.cuda.Stream()
        
        pending_results = []
        
        with torch.no_grad():
            batch_idx = 0
            while batch_idx < total_items:
                if pending_results:
                    old_batch_idx, old_end_idx, old_result, old_stream = pending_results.pop(0)
                    old_stream.synchronize()
                    all_embeddings[old_batch_idx:old_end_idx] = old_result.tolist()
                    del old_result
                
                gpu_info = get_gpu_info()
                actual_batch_size = batch_size
                
                if gpu_info.get("available"):
                    device_info = gpu_info["devices"][0]
                    free_mem = device_info["free_memory_gb"]
                    allocated_mem = device_info["allocated_memory_gb"]
                    
                    if free_mem < 1.0:
                        actual_batch_size = 4
                    elif free_mem < 1.5:
                        actual_batch_size = 8
                    elif free_mem < 2.0:
                        actual_batch_size = 16
                    elif free_mem < 3.0:
                        actual_batch_size = 32
                    elif free_mem < 5.0:
                        actual_batch_size = 64
                    else:
                        actual_batch_size = min(batch_size, 128)
                    
                    if batch_idx == 0 or actual_batch_size < batch_size // 2:
                        logger.info(f"[显存监控] 可用: {free_mem:.2f}GB, 已用: {allocated_mem:.2f}GB, 批次大小: {actual_batch_size}")
                
                end_idx = min(batch_idx + actual_batch_size, total_items)
                batch = texts[batch_idx:end_idx]
                
                with torch.cuda.stream(stream_compute):
                    features = model.tokenize(batch)
                    features = {k: v.to(device, non_blocking=True) for k, v in features.items()}
                    
                    output = model(features)
                    embeddings = output['sentence_embedding']
                    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
                    
                    result = embeddings.cpu()
                    pending_results.append((batch_idx, end_idx, result, stream_compute))
                    
                    del features, output, embeddings
                
                batch_idx = end_idx
            
            for batch_idx, end_idx, result, stream in pending_results:
                stream.synchronize()
                all_embeddings[batch_idx:end_idx] = result.tolist()
        
        torch.cuda.empty_cache()
        return all_embeddings
    
    def _encode_batch_gguf(self, texts: list[str]) -> list:
        """使用 GGUF 模型编码"""
        all_embeddings = []
        
        for text in texts:
            try:
                embedding = embedding_service.generate_embedding(text)
                if embedding:
                    all_embeddings.append(embedding)
                else:
                    all_embeddings.append(None)
            except Exception as e:
                logger.error(f"GGUF 编码失败: {e}")
                all_embeddings.append(None)
        
        return all_embeddings
    
    def _encode_batch_optimized(self, texts: list[str]) -> list:
        """使用优化的批处理编码"""
        model_type = embedding_service.model_type
        
        if model_type == "gguf":
            logger.info(f"[GGUF] 编码 {len(texts)} 条文本")
            return self._encode_batch_gguf(texts)
        
        batches = batch_optimizer.optimize_texts(texts, use_dynamic=True)
        
        bucket_stats = {"short": 0, "medium": 0, "long": 0}
        for bg in batches:
            bucket_stats[bg.bucket.value] += len(bg.items)
        
        logger.info(f"[动态批处理] 总文本数: {len(texts)}, 分成 {len(batches)} 个批次")
        logger.info(f"  分桶统计: short={bucket_stats['short']}, medium={bucket_stats['medium']}, long={bucket_stats['long']}")
        
        gpu_info = get_gpu_info()
        if gpu_info.get("available"):
            device = gpu_info["devices"][0]
            logger.info(f"  GPU显存: 总计 {device['total_memory_gb']:.1f}GB, 已用 {device['allocated_memory_gb']:.2f}GB, 可用 {device['free_memory_gb']:.1f}GB")
        
        all_embeddings = [None] * len(texts)
        total_time = 0
        processed = 0
        
        for batch_idx, batch_group in enumerate(batches):
            batch_texts = [item.text for item in batch_group.items]
            indices = [item.index for item in batch_group.items]
            
            batch_start = time.time()
            
            if batch_idx == 0:
                logger.info(f"[批次 {batch_idx+1}/{len(batches)}] 开始编码 {len(batch_texts)} 条, bucket={batch_group.bucket.value}")
            else:
                avg_time = total_time / processed if processed > 0 else 0
                remaining = len(texts) - processed
                eta = avg_time * remaining
                logger.info(f"[批次 {batch_idx+1}/{len(batches)}] 编码 {len(batch_texts)} 条, bucket={batch_group.bucket.value}, 预计剩余: {eta:.1f}s")
            
            try:
                embeddings = self._encode_batch_sync(batch_texts, batch_group.batch_size)
                
                for i, emb in enumerate(embeddings):
                    if emb:
                        all_embeddings[indices[i]] = emb
                
                batch_optimizer.dynamic_batcher.on_success()
                batch_time = time.time() - batch_start
                total_time += batch_time
                processed += len(batch_texts)
                
                speed = len(batch_texts) / batch_time if batch_time > 0 else 0
                logger.info(f"[批次 {batch_idx+1}/{len(batches)}] 完成, 耗时: {batch_time:.2f}s, 速度: {speed:.1f}条/s")
                
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    new_batch_size = batch_optimizer.dynamic_batcher.on_oom()
                    logger.warning(f"GPU OOM, 减少批次大小到 {new_batch_size}")
                    
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    
                    smaller_batches = batch_optimizer.optimize_texts(batch_texts, use_dynamic=True)
                    
                    for smaller_batch in smaller_batches:
                        smaller_texts = [item.text for item in smaller_batch.items]
                        smaller_indices = [indices[item.index] for item in smaller_batch.items]
                        
                        try:
                            emb = self._encode_batch_sync(smaller_texts, smaller_batch.batch_size)
                            for j, e in enumerate(emb):
                                if e:
                                    all_embeddings[smaller_indices[j]] = e
                        except Exception:
                            pass
                else:
                    raise
        
        success_count = sum(1 for e in all_embeddings if e is not None)
        avg_speed = len(texts) / total_time if total_time > 0 else 0
        logger.info(f"[编码完成] 总计: {len(texts)}, 成功: {success_count}, 平均速度: {avg_speed:.1f}条/s")
        return all_embeddings
    
    async def import_file(self, file_path: Path) -> KnowledgeImportResult:
        result = KnowledgeImportResult(success=True, file_path=str(file_path))
        
        if not file_path.exists():
            result.success = False
            result.errors.append("文件不存在")
            return result
        
        data = self._get_vector_data(file_path)
        if not data:
            result.success = False
            result.errors.append("无法获取向量数据")
            return result
        
        knowledge_type, vector_data = data
        
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            _gpu_executor,
            self._encode_batch_sync,
            [vector_data.content_for_embedding],
            len([vector_data.content_for_embedding])
        )
        
        if embeddings and embeddings[0]:
            success = await vector_compute_service.add_vector(knowledge_type, vector_data, embeddings[0])
            if success:
                result.knowledge_count = 1
                logger.info(f"向量存储成功: {vector_data.doc_title}")
            else:
                result.error_count = 1
                result.errors.append("向量存储失败")
        else:
            result.error_count = 1
            result.errors.append("向量生成失败")
        
        return result
    
    async def import_directory(
        self,
        directory_path: Path,
    ) -> list[KnowledgeImportResult]:
        start_time = time.time()
        
        max_workers = settings.import_max_workers
        batch_size = get_optimal_batch_size(
            model_memory_mb=600,
            safety_factor=0.5,
            min_batch_size=16,
            max_batch_size=256,
        )
        use_optimized_batch = True
        
        knowledge_type = get_knowledge_type_by_path(str(directory_path))
        if not knowledge_type:
            logger.error(f"无法识别知识类型: {directory_path}")
            return []
        
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            logger.error(f"未找到知识类型配置: {knowledge_type}")
            return []
        
        if config.vector_field == VectorFieldType.SUMMARY:
            return await self._import_from_summaries(knowledge_type)
        
        file_paths = [f for f in directory_path.glob("**/*") if f.is_file()]
        file_count = len(file_paths)
        
        logger.info(f"开始导入目录: {directory_path}, 共 {file_count} 个文件")
        print(f"[导入] 目录: {directory_path}, 文件数: {file_count}")
        
        results = [KnowledgeImportResult(success=True, file_path=str(f)) for f in file_paths]
        
        print(f"  [1/3] 并行解析文件 (线程数: {max_workers})...")
        parse_start = time.time()
        
        importer = self
        
        def parse_file(idx: int, file_path: Path) -> Optional[tuple[int, KnowledgeType, VectorData]]:
            data = importer._get_vector_data(file_path)
            if data:
                return (idx, data[0], data[1])
            return None
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            loop = asyncio.get_event_loop()
            parse_tasks = [
                loop.run_in_executor(executor, parse_file, i, fp)
                for i, fp in enumerate(file_paths)
            ]
            parse_results = await asyncio.gather(*parse_tasks)
        
        vector_items: list[tuple[int, KnowledgeType, VectorData]] = []
        for result in parse_results:
            if result:
                idx, kt, vd = result
                vector_items.append((idx, kt, vd))
                results[idx].knowledge_count = 1
        
        for i, result in enumerate(parse_results):
            if result is None:
                results[i].success = False
                results[i].errors.append("无法获取向量数据")
        
        parse_time = time.time() - parse_start
        print(f"        解析完成: {len(vector_items)} 个有效文件, 耗时: {parse_time:.2f}秒")
        
        if not vector_items:
            elapsed = time.time() - start_time
            print(f"[完成] 耗时: {elapsed:.2f}秒")
            return results
        
        print(f"  [2/3] 批量计算向量 (优化模式: {use_optimized_batch})...")
        embed_start = time.time()
        
        by_type: dict[KnowledgeType, list[tuple[int, VectorData]]] = {}
        for idx, kt, vd in vector_items:
            if kt not in by_type:
                by_type[kt] = []
            by_type[kt].append((idx, vd))
        
        all_embeddings: dict[int, list[float]] = {}
        loop = asyncio.get_event_loop()
        
        for knowledge_type, items in by_type.items():
            texts = [vd.content_for_embedding for _, vd in items]
            indices = [idx for idx, _ in items]
            
            total = len(texts)
            print(f"        {knowledge_type.value}: 计算 {total} 条向量...")
            
            if use_optimized_batch:
                embeddings = await loop.run_in_executor(
                    _gpu_executor,
                    self._encode_batch_optimized,
                    texts
                )
            else:
                embeddings = await loop.run_in_executor(
                    _gpu_executor,
                    self._encode_batch_sync,
                    texts,
                    batch_size
                )
            
            for i, emb in enumerate(embeddings):
                if emb:
                    all_embeddings[indices[i]] = emb
        
        embed_time = time.time() - embed_start
        print(f"        向量计算完成: {len(all_embeddings)} 条, 耗时: {embed_time:.2f}秒")
        
        print(f"  [3/3] 批量存储向量...")
        store_start = time.time()
        
        store_count = 0
        error_count = 0
        
        for knowledge_type, items in by_type.items():
            store_items = []
            for idx, vd in items:
                emb = all_embeddings.get(idx)
                if emb:
                    store_items.append((idx, vd, emb))
            
            if not store_items:
                continue
            
            store = vector_compute_service.get_vector_store(knowledge_type)
            if not store:
                for idx, _, _ in store_items:
                    results[idx].errors.append("向量库未初始化")
                continue
            
            store.begin_batch()
            
            docs_to_add = []
            for idx, vd, emb in store_items:
                docs_to_add.append({
                    "doc_id": vd.doc_id,
                    "content": vd.content_for_embedding,
                    "embedding": emb,
                    "metadata": {
                        "doc_id": vd.doc_id,
                        "doc_title": vd.doc_title,
                        "doc_path": vd.doc_path,
                        "doc_summary": vd.doc_summary,
                    },
                })
            
            added = await store.add_documents_batch(docs_to_add)
            store_count += added
            
            await store.end_batch()
            
            if added < len(store_items):
                error_count += len(store_items) - added
                for idx, _, _ in store_items[added:]:
                    results[idx].errors.append("向量存储失败")
        
        store_time = time.time() - store_start
        print(f"        向量存储完成: {store_count} 条, 耗时: {store_time:.2f}秒")
        
        elapsed = time.time() - start_time
        print(f"[完成] 总耗时: {elapsed:.2f}秒, 成功: {store_count}, 失败: {error_count}")
        print(f"       解析: {parse_time:.2f}s, 计算: {embed_time:.2f}s, 存储: {store_time:.2f}s")
        
        return results
    
    async def _import_from_summaries(
        self,
        knowledge_type: KnowledgeType,
    ) -> list[KnowledgeImportResult]:
        start_time = time.time()
        
        vector_datas = vector_compute_service.get_all_vector_data_for_type(knowledge_type)
        total = len(vector_datas)
        
        logger.info(f"开始从摘要导入 {knowledge_type.value}, 共 {total} 条")
        print(f"[导入] 从摘要导入 {knowledge_type.value}, 共 {total} 条")
        
        results = [KnowledgeImportResult(success=True, file_path=vd.doc_path) for vd in vector_datas]
        
        print(f"  [1/2] 批量计算向量 (优化模式)...")
        embed_start = time.time()
        
        texts = [vd.content_for_embedding for vd in vector_datas]
        print(f"        {knowledge_type.value}: 计算 {total} 条向量...")
        
        loop = asyncio.get_event_loop()
        
        all_embeddings: dict[int, list[float]] = {}
        
        batches = batch_optimizer.optimize_texts(texts, use_dynamic=True)
        
        for batch_group in batches:
            batch_texts = [item.text for item in batch_group.items]
            indices = [item.index for item in batch_group.items]
            
            try:
                embeddings = await loop.run_in_executor(
                    _gpu_executor,
                    self._encode_batch_optimized,
                    batch_texts
                )
                
                for i, emb in enumerate(embeddings):
                    if emb:
                        all_embeddings[indices[i]] = emb
            except Exception as e:
                logger.error(f"向量计算失败: {e}")
        
        embed_time = time.time() - embed_start
        print(f"        向量计算完成: {len(all_embeddings)} 条, 耗时: {embed_time:.2f}秒")
        
        print(f"  [2/2] 批量存储向量...")
        store_start = time.time()
        
        store = vector_compute_service.get_vector_store(knowledge_type)
        if not store:
            print(f"        向量库未初始化")
            return results
        
        store.begin_batch()
        
        docs_to_add = []
        for idx in range(len(vector_datas)):
            emb = all_embeddings.get(idx)
            if emb:
                docs_to_add.append({
                    "doc_id": vector_datas[idx].doc_id,
                    "content": vector_datas[idx].content_for_embedding,
                    "embedding": emb,
                    "metadata": {
                        "doc_id": vector_datas[idx].doc_id,
                        "doc_title": vector_datas[idx].doc_title,
                        "doc_path": vector_datas[idx].doc_path,
                        "doc_summary": vector_datas[idx].doc_summary,
                    },
                })
        
        added = await store.add_documents_batch(docs_to_add)
        
        await store.end_batch()
        
        store_time = time.time() - store_start
        print(f"        向量存储完成: {added} 条, 耗时: {store_time:.2f}秒")
        
        elapsed = time.time() - start_time
        print(f"[完成] 总耗时: {elapsed:.2f}秒, 成功: {added}, 失败: {total - added}")
        
        for idx in range(len(vector_datas)):
            if idx not in all_embeddings:
                results[idx].success = False
                results[idx].errors.append("向量生成失败")
        
        return results
    
    async def _import_from_summaries_pipeline(
        self,
        knowledge_type: KnowledgeType,
    ) -> list[KnowledgeImportResult]:
        """流水线模式导入摘要数据"""
        start_time = time.time()
        
        batch_size = get_optimal_batch_size(
            model_memory_mb=600,
            safety_factor=0.5,
            min_batch_size=16,
            max_batch_size=256,
        )
        
        vector_datas = vector_compute_service.get_all_vector_data_for_type(knowledge_type)
        total = len(vector_datas)
        
        if total == 0:
            return []
        
        print(f"[流水线导入] 摘要数据: {total} 条")
        logger.info(f"[流水线] 开始处理摘要 {knowledge_type.value}, 共 {total} 条")
        
        results: list[KnowledgeImportResult] = [None] * total
        
        stats = {"parse_time": 0, "encode_time": 0, "store_time": 0, "encode_count": 0, "store_count": 0}
        
        parse_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        encode_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        
        encode_done = asyncio.Event()
        
        async def parse_producer():
            """解析阶段：将摘要数据放入队列"""
            stage_start = time.time()
            
            for idx, vd in enumerate(vector_datas):
                await parse_queue.put({
                    "idx": idx,
                    "doc_id": vd.doc_id,
                    "doc_path": vd.doc_path,
                    "content": vd.content_for_embedding,
                    "doc_title": vd.doc_title,
                    "doc_summary": vd.doc_summary,
                })
            
            stats["parse_time"] = time.time() - stage_start
            await parse_queue.put(None)
            print(f"  [解析完成] 耗时: {stats['parse_time']:.2f}s, 数据: {total}")
        
        async def encode_worker():
            """编码阶段：批量计算向量"""
            stage_start = time.time()
            batch_items: list[dict] = []
            count = 0
            
            while True:
                try:
                    item = await asyncio.wait_for(parse_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    break
                
                if item is None:
                    break
                
                batch_items.append(item)
                
                if len(batch_items) >= batch_size:
                    texts = [it["content"] for it in batch_items]
                    
                    loop = asyncio.get_event_loop()
                    embeddings = await loop.run_in_executor(
                        _gpu_executor,
                        self._encode_batch_optimized,
                        texts
                    )
                    
                    for i, it in enumerate(batch_items):
                        if embeddings[i]:
                            it["embedding"] = embeddings[i]
                            await encode_queue.put(it)
                            count += 1
                        else:
                            results[it["idx"]] = KnowledgeImportResult(
                                success=False,
                                file_path=it["doc_path"],
                                errors=["编码失败"]
                            )
                    
                    batch_items = []
            
            if batch_items:
                texts = [it["content"] for it in batch_items]
                
                loop = asyncio.get_event_loop()
                embeddings = await loop.run_in_executor(
                    _gpu_executor,
                    self._encode_batch_optimized,
                    texts
                )
                
                for i, it in enumerate(batch_items):
                    if embeddings[i]:
                        it["embedding"] = embeddings[i]
                        await encode_queue.put(it)
                        count += 1
                    else:
                        results[it["idx"]] = KnowledgeImportResult(
                            success=False,
                            file_path=it["doc_path"],
                            errors=["编码失败"]
                        )
            
            stats["encode_time"] = time.time() - stage_start
            stats["encode_count"] = count
            encode_done.set()
            await encode_queue.put(None)
            print(f"  [编码完成] 耗时: {stats['encode_time']:.2f}s, 成功: {count}")
        
        async def store_consumer():
            """存储阶段：保存到向量数据库"""
            stage_start = time.time()
            
            store = vector_compute_service.get_vector_store(knowledge_type)
            if not store:
                print(f"  [存储失败] 向量库未初始化")
                return
            
            docs_to_add: list[dict] = []
            count = 0
            
            while True:
                try:
                    item = await asyncio.wait_for(encode_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if encode_done.is_set() and encode_queue.empty():
                        break
                    continue
                
                if item is None:
                    break
                
                if "embedding" in item:
                    docs_to_add.append({
                        "doc_id": item["doc_id"],
                        "content": item["content"],
                        "embedding": item["embedding"],
                        "metadata": {
                            "doc_id": item["doc_id"],
                            "doc_title": item["doc_title"],
                            "doc_path": item["doc_path"],
                            "doc_summary": item["doc_summary"],
                        },
                    })
                    
                    if len(docs_to_add) >= batch_size:
                        await store.add_documents_batch(docs_to_add)
                        count += len(docs_to_add)
                        docs_to_add = []
                    
                    results[item["idx"]] = KnowledgeImportResult(
                        success=True,
                        file_path=item["doc_path"],
                        knowledge_count=1
                    )
            
            if docs_to_add:
                await store.add_documents_batch(docs_to_add)
                count += len(docs_to_add)
            
            if store:
                await store.flush()
            
            stats["store_time"] = time.time() - stage_start
            stats["store_count"] = count
            print(f"  [存储完成] 耗时: {stats['store_time']:.2f}s, 存储: {count}")
        
        await asyncio.gather(
            parse_producer(),
            encode_worker(),
            store_consumer(),
        )
        
        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r and r.success)
        error_count = sum(1 for r in results if r and not r.success)
        
        print(f"[流水线完成] 总耗时: {elapsed:.2f}s, 成功: {success_count}, 失败: {error_count}")
        print(f"             解析: {stats['parse_time']:.2f}s, 编码: {stats['encode_time']:.2f}s ({stats['encode_count']}条), 存储: {stats['store_time']:.2f}s ({stats['store_count']}条)")
        
        return [r for r in results if r is not None]
    
    async def import_knowledge(
        self,
        request: KnowledgeImportRequest,
    ) -> KnowledgeImportResponse:
        if not self._initialized:
            await self.initialize()
        
        start_time = time.time()
        results: list[ImportResult] = []
        errors: list[str] = []
        
        source_path = Path(request.source_path)
        
        if not source_path.exists():
            return KnowledgeImportResponse(
                success=False,
                errors=[f"源路径不存在: {request.source_path}"],
            )
        
        try:
            if source_path.is_file():
                import_result = await self.import_file(source_path)
                result = ImportResult(
                    file_path=str(source_path),
                    status=ImportStatus.COMPLETED if import_result.success else ImportStatus.FAILED,
                    knowledge_name=source_path.stem,
                    chunks_count=import_result.knowledge_count,
                    error_message="; ".join(import_result.errors) if import_result.errors else None,
                )
                results.append(result)
            elif source_path.is_dir():
                dir_results = await self.import_directory(source_path)
                for r in dir_results:
                    result = ImportResult(
                        file_path=r.file_path,
                        status=ImportStatus.COMPLETED if r.success else ImportStatus.FAILED,
                        knowledge_name=Path(r.file_path).stem,
                        chunks_count=r.knowledge_count,
                        error_message="; ".join(r.errors) if r.errors else None,
                    )
                    results.append(result)
            else:
                return KnowledgeImportResponse(
                    success=False,
                    errors=["无效的源路径"],
                )
        except Exception as e:
            logger.error(f"导入过程发生错误: {e}", exc_info=True)
            errors.append(str(e))
        
        total_knowledge = sum(1 for r in results if r.status == ImportStatus.COMPLETED)
        total_chunks = sum(r.chunks_count for r in results)
        error_count = sum(1 for r in results if r.status == ImportStatus.FAILED)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return KnowledgeImportResponse(
            success=len(errors) == 0 and error_count == 0,
            results=results,
            total_knowledge=total_knowledge,
            total_chunks=total_chunks,
            error_count=error_count + len(errors),
            errors=errors,
            processing_time_ms=processing_time_ms,
        )
    
    async def manage_knowledge(
        self,
        request: KnowledgeManageRequest,
    ) -> KnowledgeManageResponse:
        if not self._initialized:
            await self.initialize()
        
        try:
            if request.action == ManageAction.REBUILD_INDEX:
                stats = await self.rebuild_index()
                return KnowledgeManageResponse(
                    success=True,
                    action=request.action,
                    data=stats,
                    message="索引重建完成",
                )
            
            elif request.action == ManageAction.CLEAR_ALL:
                stats = await self.rebuild_index()
                return KnowledgeManageResponse(
                    success=True,
                    action=request.action,
                    data=stats,
                    message="清空完成",
                )
            
            return KnowledgeManageResponse(
                success=False,
                action=request.action,
                message="未知操作",
            )
            
        except Exception as e:
            logger.error(f"管理操作失败: {e}", exc_info=True)
            return KnowledgeManageResponse(
                success=False,
                action=request.action,
                message=str(e),
            )
    
    async def rebuild_index(self) -> dict[str, Any]:
        logger.info("开始重建向量索引")
        await vector_compute_service.clear_all()
        stats = await vector_compute_service.get_statistics()
        logger.info(f"向量索引重建完成: {stats}")
        return stats
    
    async def get_statistics(self) -> KnowledgeStatistics:
        if not self._initialized:
            await self.initialize()
        
        stats = await vector_compute_service.get_statistics()
        
        return KnowledgeStatistics(
            total_knowledge=stats.get("total_count", 0),
            total_chunks=stats.get("faiss_chunks", 0),
            by_type=stats.get("by_type", {}),
            by_source=stats.get("by_source", {}),
            vector_store_status={"total_chunks": stats.get("faiss_chunks", 0)},
        )
    
    def get_optimization_stats(self) -> dict[str, Any]:
        """获取优化统计信息"""
        return batch_optimizer.get_statistics()
    
    async def import_directory_pipeline(
        self,
        directory: Path,
    ) -> list[KnowledgeImportResult]:
        """流水线并行导入：解析、编码、存储三阶段真正并行"""
        start_time = time.time()
        
        batch_size = get_optimal_batch_size(
            model_memory_mb=600,
            safety_factor=0.5,
            min_batch_size=16,
            max_batch_size=256,
        )
        
        knowledge_type = get_knowledge_type_by_path(str(directory))
        if not knowledge_type:
            logger.error(f"无法识别知识类型: {directory}")
            return []
        
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            logger.error(f"未找到知识类型配置: {knowledge_type}")
            return []
        
        if config.vector_field == VectorFieldType.SUMMARY:
            print(f"[流水线导入] 摘要模式: {knowledge_type.value}")
            return await self._import_from_summaries_pipeline(knowledge_type)
        
        files = [f for f in directory.glob("**/*") if f.is_file() and f.suffix.lower() == ".md"]
        total = len(files)
        
        if total == 0:
            return []
        
        print(f"[流水线导入] 共 {total} 个文件")
        logger.info(f"[流水线] 开始处理 {total} 个文件")
        
        parse_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        encode_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        
        results: list[KnowledgeImportResult] = [None] * total
        
        stats = {"parse_time": 0, "encode_time": 0, "store_time": 0, "parse_count": 0, "encode_count": 0, "store_count": 0}
        
        parse_done = asyncio.Event()
        encode_done = asyncio.Event()
        
        async def parse_producer():
            """解析阶段：读取文件并解析为向量数据，放入解析队列"""
            stage_start = time.time()
            count = 0
            
            for idx, file_path in enumerate(files):
                try:
                    result = self._get_vector_data(file_path)
                    
                    if result:
                        knowledge_type, vector_data = result
                        await parse_queue.put({
                            "idx": idx,
                            "file_path": str(file_path),
                            "knowledge_type": knowledge_type,
                            "vector_data": vector_data,
                        })
                        count += 1
                    else:
                        results[idx] = KnowledgeImportResult(
                            success=False,
                            file_path=str(file_path),
                            errors=["解析失败"]
                        )
                    
                    if (idx + 1) % 5000 == 0:
                        print(f"  [解析] 进度: {idx + 1}/{total}")
                        
                except Exception as e:
                    logger.error(f"解析文件失败 {file_path}: {e}")
                    results[idx] = KnowledgeImportResult(
                        success=False,
                        file_path=str(file_path),
                        errors=[str(e)]
                    )
            
            stats["parse_time"] = time.time() - stage_start
            stats["parse_count"] = count
            parse_done.set()
            await parse_queue.put(None)
            print(f"  [解析完成] 耗时: {stats['parse_time']:.2f}s, 成功: {count}")
        
        async def encode_worker():
            """编码阶段：从解析队列取数据，批量计算向量，放入编码队列"""
            stage_start = time.time()
            batch_items: list[dict] = []
            count = 0
            
            while True:
                try:
                    item = await asyncio.wait_for(parse_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if parse_done.is_set() and parse_queue.empty():
                        break
                    continue
                
                if item is None:
                    break
                
                batch_items.append(item)
                
                if len(batch_items) >= batch_size:
                    texts = [it["vector_data"].content_for_embedding for it in batch_items]
                    
                    loop = asyncio.get_event_loop()
                    embeddings = await loop.run_in_executor(
                        _gpu_executor,
                        self._encode_batch_optimized,
                        texts
                    )
                    
                    for i, it in enumerate(batch_items):
                        if embeddings[i]:
                            it["embedding"] = embeddings[i]
                            await encode_queue.put(it)
                            count += 1
                        else:
                            results[it["idx"]] = KnowledgeImportResult(
                                success=False,
                                file_path=it["file_path"],
                                errors=["编码失败"]
                            )
                    
                    batch_items = []
            
            if batch_items:
                texts = [it["vector_data"].content_for_embedding for it in batch_items]
                
                loop = asyncio.get_event_loop()
                embeddings = await loop.run_in_executor(
                    _gpu_executor,
                    self._encode_batch_optimized,
                    texts
                )
                
                for i, it in enumerate(batch_items):
                    if embeddings[i]:
                        it["embedding"] = embeddings[i]
                        await encode_queue.put(it)
                        count += 1
                    else:
                        results[it["idx"]] = KnowledgeImportResult(
                            success=False,
                            file_path=it["file_path"],
                            errors=["编码失败"]
                        )
            
            stats["encode_time"] = time.time() - stage_start
            stats["encode_count"] = count
            encode_done.set()
            await encode_queue.put(None)
            print(f"  [编码完成] 耗时: {stats['encode_time']:.2f}s, 成功: {count}")
        
        async def store_consumer():
            """存储阶段：从编码队列取数据，存储到向量数据库"""
            stage_start = time.time()
            
            current_type: Optional[KnowledgeType] = None
            current_store = None
            docs_to_add: list[dict] = []
            count = 0
            
            while True:
                try:
                    item = await asyncio.wait_for(encode_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if encode_done.is_set() and encode_queue.empty():
                        break
                    continue
                
                if item is None:
                    break
                
                if current_type != item["knowledge_type"]:
                    if current_store and docs_to_add:
                        await current_store.add_documents_batch(docs_to_add)
                        count += len(docs_to_add)
                        docs_to_add = []
                    
                    current_type = item["knowledge_type"]
                    current_store = vector_compute_service.get_vector_store(current_type)
                
                if current_store and "embedding" in item:
                    docs_to_add.append({
                        "doc_id": item["vector_data"].doc_id,
                        "content": item["vector_data"].content_for_embedding,
                        "embedding": item["embedding"],
                        "metadata": {
                            "doc_id": item["vector_data"].doc_id,
                            "doc_title": item["vector_data"].doc_title,
                            "doc_path": item["vector_data"].doc_path,
                            "doc_summary": item["vector_data"].doc_summary,
                        },
                    })
                    
                    if len(docs_to_add) >= batch_size:
                        await current_store.add_documents_batch(docs_to_add)
                        count += len(docs_to_add)
                        docs_to_add = []
                    
                    results[item["idx"]] = KnowledgeImportResult(
                        success=True,
                        file_path=item["file_path"],
                        knowledge_count=1
                    )
            
            if current_store and docs_to_add:
                await current_store.add_documents_batch(docs_to_add)
                count += len(docs_to_add)
            
            if current_store:
                await current_store.flush()
            
            stats["store_time"] = time.time() - stage_start
            stats["store_count"] = count
            print(f"  [存储完成] 耗时: {stats['store_time']:.2f}s, 存储: {count}")
        
        await asyncio.gather(
            parse_producer(),
            encode_worker(),
            store_consumer(),
        )
        
        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r and r.success)
        error_count = sum(1 for r in results if r and not r.success)
        
        print(f"[流水线完成] 总耗时: {elapsed:.2f}s, 成功: {success_count}, 失败: {error_count}")
        print(f"             解析: {stats['parse_time']:.2f}s ({stats['parse_count']}条), 编码: {stats['encode_time']:.2f}s ({stats['encode_count']}条), 存储: {stats['store_time']:.2f}s ({stats['store_count']}条)")
        
        return [r for r in results if r is not None]


knowledge_importer = KnowledgeImporter()

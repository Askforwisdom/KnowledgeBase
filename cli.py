#!/usr/bin/env python3
"""
知识库管理命令行工具
提供导入、查询、统计、SDK向量索引等功能
"""
import asyncio
import argparse
import logging
from pathlib import Path

from src.services.import_ import (
    knowledge_importer,
    ManageAction,
    KnowledgeManageRequest,
)
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def import_command(args):
    """导入知识"""
    print(f"开始导入: {args.path}")
    
    from pathlib import Path
    results = await knowledge_importer.import_directory_pipeline(
        directory=Path(args.path),
    )
    success_count = sum(1 for r in results if r.success)
    print(f"\n✓ 导入完成")
    print(f"  成功: {success_count} 条")
    print(f"  失败: {len(results) - success_count} 条")


async def query_command(args):
    """查询知识"""
    from src.services.search.vector_searcher import vector_searcher
    from src.models.knowledge import KnowledgeType, get_knowledge_type_config
    
    queries = args.query if isinstance(args.query, list) else [args.query]
    print(f"查询: {queries}")
    
    try:
        kt = KnowledgeType(args.type)
    except ValueError:
        print(f"✗ 无效的知识类型: {args.type}")
        return
    
    config = get_knowledge_type_config(kt)
    if not config:
        print(f"✗ 未找到知识类型配置: {args.type}")
        return
    
    import asyncio
    search_tasks = [
        vector_searcher.search(
            query=q,
            k=args.limit,
            min_score=config.search_min_score,
            knowledge_types=[kt],
        )
        for q in queries
    ]
    
    all_results = await asyncio.gather(*search_tasks)
    
    seen_paths = set()
    unique_results = []
    for results in all_results:
        for r in results:
            if r.doc_path and r.doc_path not in seen_paths:
                seen_paths.add(r.doc_path)
                unique_results.append(r)

    print(f"找到 {len(unique_results)} 条结果:")
    for i, result in enumerate(unique_results, 1):
        print(f"\n{i}. {result.doc_title}")
        print(f"   路径: {result.doc_path}")
        print(f"   相似度: {result.score:.4f}")
        if result.doc_summary:
            print(f"   摘要: {result.doc_summary[:100]}...")


async def stats_command(args):
    """显示统计信息"""
    stats = await knowledge_importer.get_statistics()

    print("知识库统计信息:")
    print(f"  总数量: {stats.total_knowledge}")
    print(f"  分块数: {stats.total_chunks}")
    print("\n按类型分布:")
    for ktype, count in stats.by_type.items():
        print(f"  {ktype}: {count}")
    print("\n按来源分布:")
    for source, count in stats.by_source.items():
        print(f"  {source}: {count}")


async def entity_command(args):
    """获取实体信息"""
    print(f"实体查询功能暂时不可用: {args.name}")


async def sdk_build_command(args):
    """构建SDK向量索引"""
    from src.services.import_.sdk_vector_store import sdk_vector_store
    from src.services.import_.embedder import EmbeddingGenerator
    
    model_key = args.model
    batch_size = args.batch_size
    
    print(f"开始构建SDK向量索引")
    print(f"  嵌入模型: {model_key}")
    print(f"  批次大小: {batch_size}")
    
    model_config = settings.get_embedding_model_config(model_key)
    model_path = model_config.get("name")
    dimension = model_config.get("dimension", 1024)
    
    if not model_path:
        print(f"✗ 嵌入模型未配置: {model_key}")
        return
    
    print(f"  模型路径: {model_path}")
    print(f"  向量维度: {dimension}")
    
    try:
        from sentence_transformers import SentenceTransformer
        print("  加载嵌入模型...")
        model = SentenceTransformer(model_path)
        model.model_name = model_key
        print("  ✓ 嵌入模型加载成功")
    except Exception as e:
        print(f"✗ 加载嵌入模型失败: {e}")
        return
    
    embedder = EmbeddingGenerator(model)
    
    sdk_vector_store.dimension = dimension
    await sdk_vector_store.initialize()
    
    print("  开始生成向量索引...")
    result = await sdk_vector_store.build_index(embedder, batch_size=batch_size)
    
    if result.get("success"):
        stats = result.get("stats", {})
        print(f"\n✓ 索引构建完成")
        print(f"  总数: {stats.get('total', 0)}")
        print(f"  成功: {stats.get('success', 0)}")
        print(f"  失败: {stats.get('failed', 0)}")
        print(f"  跳过: {stats.get('skipped', 0)}")
    else:
        print(f"\n✗ 索引构建失败: {result.get('error')}")


async def sdk_search_command(args):
    """搜索SDK文档"""
    from src.services.import_.sdk_vector_store import sdk_vector_store
    from src.services.import_.embedder import EmbeddingGenerator
    
    model_key = args.model
    
    model_config = settings.get_embedding_model_config(model_key)
    model_path = model_config.get("name")
    
    if not model_path:
        print(f"✗ 嵌入模型未配置: {model_key}")
        return
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_path)
        model.model_name = model_key
    except Exception as e:
        print(f"✗ 加载嵌入模型失败: {e}")
        return
    
    embedder = EmbeddingGenerator(model)
    
    await sdk_vector_store.initialize()
    
    print(f"搜索: {args.query}")
    query_embedding = embedder.generate(args.query)
    
    if not query_embedding:
        print("✗ 生成查询向量失败")
        return
    
    results = await sdk_vector_store.search(
        query_embedding=query_embedding,
        k=args.top_k,
        min_score=args.min_score,
    )
    
    print(f"\n找到 {len(results)} 条结果:")
    print("-" * 80)
    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r['doc_title']}")
        print(f"    路径: {r['doc_path']}")
        print(f"    相似度: {r['score']:.4f}")
        print(f"    摘要: {r['summary'][:150]}...")
        if r.get('core_classes'):
            print(f"    核心类: {', '.join(r['core_classes'][:3])}")


async def sdk_stats_command(args):
    """显示SDK向量索引统计"""
    from src.services.import_.sdk_vector_store import sdk_vector_store
    
    await sdk_vector_store.initialize()
    stats = await sdk_vector_store.get_statistics()
    
    print("\nSDK向量索引统计:")
    print(f"  摘要总数: {stats.get('total_summaries', 0)}")
    print(f"  已索引: {stats.get('indexed', 0)}")


async def sdk_clean_command(args):
    """清理SDK相关旧数据"""
    from src.services.faiss_store import faiss_store
    from src.storage.database import async_session_factory
    from src.storage.models import KnowledgeEntity, KnowledgeChunkEntity
    
    dry_run = args.dry_run
    
    if dry_run:
        print("=" * 60)
        print("DRY RUN 模式 - 不会实际删除数据")
        print("=" * 60)
    else:
        print("开始清理SDK相关旧数据...")
    
    stats = {
        "knowledge_deleted": 0,
        "chunks_deleted": 0,
        "vectors_deleted": 0,
    }
    
    async with async_session_factory() as session:
        knowledge_result = await session.execute(
            KnowledgeEntity.__table__.delete().where(
                KnowledgeEntity.knowledge_type == "sdk_doc"
            )
        )
        stats["knowledge_deleted"] = knowledge_result.rowcount
        
        chunks_result = await session.execute(
            KnowledgeChunkEntity.__table__.delete().where(
                KnowledgeChunkEntity.knowledge_type == "sdk_doc"
            )
        )
        stats["chunks_deleted"] = chunks_result.rowcount
        
        if not dry_run:
            await session.commit()
    
    await faiss_store.initialize()
    
    doc_ids_to_delete = []
    for doc_id, doc in faiss_store.documents.items():
        if doc.metadata.get("knowledge_type") == "sdk_doc":
            doc_ids_to_delete.append(doc_id)
    
    stats["vectors_deleted"] = len(doc_ids_to_delete)
    
    if not dry_run:
        for doc_id in doc_ids_to_delete:
            await faiss_store.delete_document(doc_id)
    
    print(f"\n清理统计:")
    print(f"  SDK知识记录: {stats['knowledge_deleted']} 条")
    print(f"  SDK分块记录: {stats['chunks_deleted']} 条")
    print(f"  SDK向量: {stats['vectors_deleted']} 个")
    
    if dry_run:
        print("\n使用 --confirm 执行实际删除")


async def main():
    parser = argparse.ArgumentParser(description="金蝶知识库管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    import_parser = subparsers.add_parser("import", help="导入知识")
    import_parser.add_argument("path", help="文件或目录路径")
    import_parser.set_defaults(func=import_command)

    query_parser = subparsers.add_parser("query", help="查询知识")
    query_parser.add_argument("query", nargs="+", help="查询文本(支持多个关键词)")
    query_parser.add_argument("--type", "-t", default="form_structure", help="知识类型 (form_structure, sdk_doc)")
    query_parser.add_argument("--limit", type=int, default=10, help="返回结果数量")
    query_parser.set_defaults(func=query_command)

    stats_parser = subparsers.add_parser("stats", help="显示统计信息")
    stats_parser.set_defaults(func=stats_command)

    entity_parser = subparsers.add_parser("entity", help="获取实体信息")
    entity_parser.add_argument("name", help="实体名称")
    entity_parser.set_defaults(func=entity_command)

    sdk_parser = subparsers.add_parser("sdk", help="SDK向量索引管理")
    sdk_subparsers = sdk_parser.add_subparsers(dest="sdk_command", help="SDK子命令")
    
    sdk_build_parser = sdk_subparsers.add_parser("build", help="构建SDK向量索引")
    sdk_build_parser.add_argument("--model", "-m", default="qwen3", help="嵌入模型名称")
    sdk_build_parser.add_argument("--batch-size", "-b", type=int, default=32, help="批量处理大小")
    sdk_build_parser.set_defaults(func=sdk_build_command)
    
    sdk_search_parser = sdk_subparsers.add_parser("search", help="搜索SDK文档")
    sdk_search_parser.add_argument("query", help="查询文本")
    sdk_search_parser.add_argument("--model", "-m", default="qwen3", help="嵌入模型名称")
    sdk_search_parser.add_argument("--top-k", "-k", type=int, default=5, help="返回结果数量")
    sdk_search_parser.add_argument("--min-score", "-s", type=float, default=0.0, help="最小相似度阈值")
    sdk_search_parser.set_defaults(func=sdk_search_command)
    
    sdk_stats_parser = sdk_subparsers.add_parser("stats", help="显示SDK索引统计")
    sdk_stats_parser.set_defaults(func=sdk_stats_command)
    
    sdk_clean_parser = sdk_subparsers.add_parser("clean", help="清理SDK旧数据")
    sdk_clean_parser.add_argument("--dry-run", action="store_true", default=False, help="仅预览不实际删除")
    sdk_clean_parser.add_argument("--confirm", action="store_true", help="确认执行删除")
    sdk_clean_parser.set_defaults(func=sdk_clean_command)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return
    
    if args.command == "sdk" and not args.sdk_command:
        sdk_parser.print_help()
        return

    await knowledge_importer.initialize()
    await args.func(args)


if __name__ == "__main__":
    asyncio.run(main())

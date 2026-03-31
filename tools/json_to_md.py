#!/usr/bin/env python3
"""
表单数据转换工具
将 TK_NYLQ_FORMSTRUCTUR.json 格式的表单数据转换为 MD 文件

输入 JSON 格式：
{
  "RECORDS": [
    {
      "FK_NYLQ_NUMBER": "表单标识",
      "FK_NYLQ_NAME": "表单名称",
      "FK_NYLQ_STRUCTURE_TAG": "表单结构MD内容"
    },
    ...
  ]
}

输出：每个表单一个 MD 文件，放入 OriginalKnowledgeData/formStructure 目录
"""
import argparse
import json
import os
import re
from pathlib import Path
from datetime import datetime


def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def generate_md_content(form_data: dict, include_ai_placeholder: bool = True) -> str:
    """
    生成 MD 文件内容
    
    Args:
        form_data: 表单数据字典
        include_ai_placeholder: 是否包含 AI 功能描述占位符
    
    Returns:
        MD 格式的文本内容
    """
    form_id = form_data.get('FK_NYLQ_NUMBER', 'unknown')
    form_name = form_data.get('FK_NYLQ_NAME', '未命名表单')
    form_structure = form_data.get('FK_NYLQ_STRUCTURE_TAG', '')
    
    # 如果 form_structure 已经是完整的 MD 内容，直接使用
    if form_structure.strip().startswith('#'):
        # 已经是完整的 MD 格式，检查是否需要补充 AI 描述
        if include_ai_placeholder and '## 功能描述' not in form_structure:
            # 在第一个 ## 之前插入 AI 占位符
            lines = form_structure.split('\n')
            insert_index = 0
            for i, line in enumerate(lines):
                if line.startswith('##'):
                    insert_index = i
                    break
            
            ai_sections = [
                "",
                "## 功能描述",
                "",
                "<!-- AI_GENERATED_DESCRIPTION -->",
                "<!-- 待 AI 自动生成功能描述 -->",
                "",
                "## 业务场景",
                "",
                "<!-- AI_GENERATED_SCENARIOS -->",
                "<!-- 待 AI 自动生成业务场景 -->",
                "",
            ]
            
            lines = lines[:insert_index] + ai_sections + lines[insert_index:]
            return '\n'.join(lines)
        
        return form_structure
    
    # 否则构建新的 MD 内容
    lines = []
    
    # 标题
    lines.append(f"# {form_name}")
    lines.append("")
    lines.append(f"**表单标识**: `{form_id}`")
    lines.append("")
    
    # AI 功能描述占位符
    if include_ai_placeholder:
        lines.append("## 功能描述")
        lines.append("")
        lines.append("<!-- AI_GENERATED_DESCRIPTION -->")
        lines.append("<!-- 待 AI 自动生成功能描述 -->")
        lines.append("")
        
        lines.append("## 业务场景")
        lines.append("")
        lines.append("<!-- AI_GENERATED_SCENARIOS -->")
        lines.append("<!-- 待 AI 自动生成业务场景 -->")
        lines.append("")
    
    # 表单结构内容
    lines.append("## 字段信息")
    lines.append("")
    
    if form_structure:
        lines.append(form_structure)
    else:
        lines.append("<!-- 无字段信息 -->")
    
    lines.append("")
    
    # 元数据
    lines.append("---")
    lines.append("")
    lines.append(f"- **创建时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **数据来源**: Oracle 数据库导出")
    lines.append("")
    
    return '\n'.join(lines)


def convert_json_to_md(
    input_file: str,
    output_dir: str,
    include_ai_placeholder: bool = True,
    file_prefix: str = ""
) -> dict:
    """
    将 JSON 文件转换为 MD 文件
    
    Args:
        input_file: 输入 JSON 文件路径
        output_dir: 输出目录
        include_ai_placeholder: 是否包含 AI 占位符
        file_prefix: 文件名前缀
    
    Returns:
        转换统计信息
    """
    # 读取 JSON 文件
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 提取 RECORDS 数组
    if isinstance(data, dict):
        if 'RECORDS' in data:
            records = data['RECORDS']
        elif 'data' in data:
            records = data['data']
        elif 'forms' in data:
            records = data['forms']
        else:
            records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError("JSON 格式错误：期望包含 RECORDS 的对象或列表")
    
    if not isinstance(records, list):
        raise ValueError("JSON 格式错误：RECORDS 应为数组")
    
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 转换统计
    stats = {
        'total': len(records),
        'success': 0,
        'failed': 0,
        'files': []
    }
    
    # 转换每个表单
    for i, form_data in enumerate(records):
        try:
            form_id = form_data.get('FK_NYLQ_NUMBER', form_data.get('form_id', f'unknown_{i}'))
            form_name = form_data.get('FK_NYLQ_NAME', form_data.get('form_name', '未命名'))
            
            # 生成文件名
            safe_id = sanitize_filename(str(form_id))
            safe_name = sanitize_filename(str(form_name))
            filename = f"{file_prefix}{safe_id}_{safe_name}.md"
            filepath = output_path / filename
            
            # 生成 MD 内容
            md_content = generate_md_content(form_data, include_ai_placeholder)
            
            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
            
            stats['success'] += 1
            stats['files'].append(str(filepath))
            print(f"✓ 生成: {filename}")
            
        except Exception as e:
            stats['failed'] += 1
            form_id = form_data.get('FK_NYLQ_NUMBER', form_data.get('form_id', 'unknown'))
            print(f"✗ 失败: {form_id} - {str(e)}")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='将 TK_NYLQ_FORMSTRUCTUR.json 格式的表单数据转换为 MD 文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 转换默认文件
  python tools/json_to_md.py
  
  # 指定输入输出
  python tools/json_to_md.py input.json -o output_dir
  
  # 不包含 AI 占位符
  python tools/json_to_md.py --no-ai-placeholder

JSON 输入格式:
  {
    "RECORDS": [
      {
        "FK_NYLQ_NUMBER": "表单标识",
        "FK_NYLQ_NAME": "表单名称",
        "FK_NYLQ_STRUCTURE_TAG": "表单结构MD内容"
      }
    ]
  }
        """
    )
    
    parser.add_argument('input', nargs='?', 
                        default='OriginalKnowledgeData/TK_NYLQ_FORMSTRUCTUR.json',
                        help='输入 JSON 文件路径 (默认: OriginalKnowledgeData/TK_NYLQ_FORMSTRUCTUR.json)')
    parser.add_argument('-o', '--output', 
                        default='OriginalKnowledgeData/formStructure',
                        help='输出目录 (默认: OriginalKnowledgeData/formStructure)')
    parser.add_argument('--no-ai-placeholder', action='store_true', 
                        help='不包含 AI 功能描述占位符')
    parser.add_argument('--prefix', default='', 
                        help='文件名前缀')
    
    args = parser.parse_args()
    
    # 检查输入文件
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在 - {args.input}")
        return
    
    # 执行转换
    print(f"开始转换: {args.input}")
    print(f"输出目录: {args.output}")
    print("-" * 50)
    
    stats = convert_json_to_md(
        input_file=args.input,
        output_dir=args.output,
        include_ai_placeholder=not args.no_ai_placeholder,
        file_prefix=args.prefix
    )
    
    print("-" * 50)
    print(f"转换完成: 成功 {stats['success']}, 失败 {stats['failed']}, 总计 {stats['total']}")
    print(f"\n下一步:")
    print(f"  1. 检查生成的 MD 文件: {args.output}")
    print(f"  2. 使用 AI 补充功能描述: python tools/ai_describe_forms.py {args.output}")
    print(f"  3. 导入知识库: python cli.py import {args.output}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
表单功能描述自动生成工具
根据表单名称和字段信息，自动生成功能描述和业务场景

支持两种模式：
1. 规则模板模式（默认）：基于字段特征和命名规则生成描述
2. AI 模式：调用本地大模型生成描述（需要模型支持）
"""
import argparse
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


# 业务领域关键词映射
BUSINESS_DOMAINS = {
    "财务": ["财务", "会计", "账簿", "凭证", "科目", "核算", "成本", "预算", "资金", "现金", "银行", "报销", "费用", "发票", "税务", "税", "利润", "资产", "负债", "收入", "支出"],
    "供应链": ["采购", "供应商", "物料", "库存", "仓库", "入库", "出库", "发货", "收货", "订单", "合同", "招标", "投标", "寻源"],
    "生产": ["生产", "车间", "工序", "工艺", "质检", "检验", "维修", "设备", "保养", "计划", "排程", "工单"],
    "销售": ["销售", "客户", "订单", "渠道", "价格", "促销", "营销", "零售", "门店", "会员"],
    "人力": ["员工", "人员", "入职", "离职", "考勤", "薪资", "工资", "绩效", "培训", "招聘", "档案", "职位", "部门"],
    "项目": ["项目", "任务", "计划", "进度", "里程碑", "甘特图", "资源", "工时"],
    "资产": ["资产", "设备", "固定资产", "折旧", "盘点", "领用", "归还", "报废"],
    "审批": ["审批", "审核", "流程", "节点", "待办", "已办", "驳回", "通过"],
    "基础": ["组织", "用户", "角色", "权限", "参数", "配置", "模板", "档案", "分类"],
    "集成": ["接口", "API", "连接", "同步", "导入", "导出", "映射", "转换"],
    "监控": ["监控", "日志", "预警", "异常", "任务", "调度", "执行", "进度"],
    "报表": ["报表", "报告", "查询", "统计", "分析", "图表", "打印", "导出"],
    "单据": ["单据", "票据", "发票", "收据", "凭证", "编号", "状态"],
    "合同": ["合同", "协议", "条款", "签订", "变更", "终止", "续签"],
    "质量": ["质量", "检验", "检测", "标准", "合格", "不合格", "整改"],
    "服务": ["服务", "请求", "工单", "响应", "处理", "反馈", "评价"],
}

# 功能描述模板
DESCRIPTION_TEMPLATES = {
    "报告": "{name}用于生成和管理{domain}相关报告，支持报告创建、查询和导出功能。",
    "查询": "{name}用于{domain}数据的查询和检索，支持多条件筛选和数据导出。",
    "设置": "{name}用于配置{domain}相关参数和规则，支持参数维护和生效控制。",
    "列表": "{name}用于展示和管理{domain}列表数据，支持列表查询、筛选和操作。",
    "详情": "{name}用于展示{domain}详细信息，支持信息查看和维护。",
    "编辑": "{name}用于{domain}信息的编辑和维护，支持数据新增、修改和删除。",
    "选择": "{name}用于{domain}数据的选择和引用，支持快速检索和关联。",
    "申请": "{name}用于{domain}相关申请流程，支持申请提交、审批和跟踪。",
    "审批": "{name}用于{domain}审批流程管理，支持审批发起、流转和记录。",
    "台账": "{name}用于记录和管理{domain}台账数据，支持台账登记、查询和统计。",
    "单据": "{name}用于{domain}单据处理，支持单据创建、审核和归档。",
    "模板": "{name}用于{domain}模板管理，支持模板创建、复制和应用。",
    "配置": "{name}用于{domain}配置管理，支持配置项设置和生效。",
    "记录": "{name}用于记录{domain}操作日志，支持日志查询和追溯。",
    "任务": "{name}用于{domain}任务管理，支持任务创建、分配和跟踪。",
    "默认": "{name}用于{domain}业务处理，支持数据管理和流程控制。",
}

# 业务场景模板
SCENARIO_TEMPLATES = {
    "创建": "创建新的{name}记录",
    "查询": "查询和检索{name}数据",
    "修改": "修改和更新{name}信息",
    "删除": "删除作废的{name}记录",
    "审批": "提交{name}进行审批",
    "审核": "审核{name}申请",
    "导出": "导出{name}数据报表",
    "打印": "打印{name}相关文档",
    "统计": "统计分析{name}数据",
    "配置": "配置{name}相关参数",
    "导入": "批量导入{name}数据",
    "分配": "分配{name}资源或任务",
    "跟踪": "跟踪{name}处理进度",
    "监控": "监控{name}运行状态",
    "预警": "设置{name}预警规则",
}


def detect_domain(form_name: str, field_names: list) -> str:
    """检测业务领域"""
    combined_text = form_name + " ".join(field_names)
    
    for domain, keywords in BUSINESS_DOMAINS.items():
        for keyword in keywords:
            if keyword in combined_text:
                return domain
    
    return "业务"


def detect_type(form_name: str) -> str:
    """检测表单类型"""
    for type_name in DESCRIPTION_TEMPLATES.keys():
        if type_name in form_name:
            return type_name
    return "默认"


def generate_description(form_name: str, form_id: str, fields: list) -> str:
    """生成功能描述"""
    domain = detect_domain(form_name, [f.get("name", "") for f in fields])
    form_type = detect_type(form_name)
    
    template = DESCRIPTION_TEMPLATES.get(form_type, DESCRIPTION_TEMPLATES["默认"])
    
    description = template.format(name=form_name, domain=domain)
    
    key_fields = []
    for field in fields[:5]:
        field_name = field.get("name", "")
        if field_name and field_name not in ["创建人", "修改人", "创建时间", "修改时间", "审核人", "审核日期"]:
            key_fields.append(field_name)
    
    if key_fields:
        description += f"主要包含{', '.join(key_fields[:3])}等关键字段。"
    
    return description


def generate_scenarios(form_name: str, fields: list) -> list:
    """生成业务场景"""
    scenarios = []
    field_names = [f.get("name", "") for f in fields]
    combined = form_name + " ".join(field_names)
    
    if "创建" in combined or "新增" in combined or "billno" in str(field_names).lower():
        scenarios.append(f"创建新的{form_name}记录")
    
    if "查询" in combined or "列表" in combined or "检索" in combined:
        scenarios.append(f"查询和检索{form_name}数据")
    
    if "审批" in combined or "审核" in combined or "billstatus" in str(field_names).lower():
        scenarios.append(f"提交{form_name}进行审批流程")
    
    if "修改" in combined or "编辑" in combined:
        scenarios.append(f"修改和更新{form_name}信息")
    
    if "导出" in combined or "打印" in combined:
        scenarios.append(f"导出或打印{form_name}报表")
    
    if "状态" in field_names:
        scenarios.append(f"跟踪{form_name}状态变更")
    
    if "组织" in field_names:
        scenarios.append(f"按组织维度管理{form_name}")
    
    if "金额" in field_names or "费用" in field_names:
        scenarios.append(f"统计和分析{form_name}金额数据")
    
    if "日期" in field_names or "时间" in field_names:
        scenarios.append(f"按时间范围筛选{form_name}")
    
    if not scenarios:
        scenarios = [
            f"创建和管理{form_name}记录",
            f"查询{form_name}详细信息",
            f"维护{form_name}基础数据",
        ]
    
    return scenarios[:5]


def parse_md_fields(content: str) -> list:
    """解析 MD 文件中的字段信息"""
    fields = []
    
    table_match = re.search(r'\| 层级 \|.*?\n([\s\S]*?)(?=\n---|\n##|\Z)', content)
    if table_match:
        table_content = table_match.group(1)
        for line in table_content.strip().split('\n'):
            if line.startswith('|') and not line.startswith('| 层级'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 5:
                    field_name = parts[3]
                    if field_name and field_name != "字段名称":
                        fields.append({
                            "name": field_name,
                            "path": parts[2].replace('`', ''),
                            "type": parts[4],
                        })
    
    return fields


def extract_form_info(content: str) -> tuple:
    """提取表单基本信息"""
    form_name = "未命名表单"
    form_id = "unknown"
    
    name_match = re.search(r'^# (.+?) (.+?) 数据结构文档', content)
    if name_match:
        form_name = name_match.group(1).strip()
        form_id = name_match.group(2).strip()
    
    return form_name, form_id


def update_md_file(filepath: Path, use_ai: bool = False) -> bool:
    """更新 MD 文件，填充功能描述和业务场景"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if '<!-- AI_GENERATED_DESCRIPTION -->' not in content:
            return False
        
        form_name, form_id = extract_form_info(content)
        fields = parse_md_fields(content)
        
        description = generate_description(form_name, form_id, fields)
        scenarios = generate_scenarios(form_name, fields)
        
        scenarios_text = "\n".join([f"- {s}" for s in scenarios])
        
        new_content = content
        new_content = new_content.replace(
            '<!-- AI_GENERATED_DESCRIPTION -->\n<!-- 待 AI 自动生成功能描述 -->',
            description
        )
        new_content = new_content.replace(
            '<!-- AI_GENERATED_SCENARIOS -->\n<!-- 待 AI 自动生成业务场景 -->',
            scenarios_text
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True
    except Exception as e:
        print(f"  处理失败: {filepath.name} - {str(e)}")
        return False


def process_directory(directory: str, use_ai: bool = False) -> dict:
    """处理目录下所有 MD 文件"""
    dir_path = Path(directory)
    
    if not dir_path.exists():
        print(f"错误: 目录不存在 - {directory}")
        return {"total": 0, "success": 0, "failed": 0}
    
    md_files = list(dir_path.glob("*.md"))
    
    stats = {
        "total": len(md_files),
        "success": 0,
        "failed": 0,
    }
    
    print(f"开始处理: {directory}")
    print(f"共 {stats['total']} 个 MD 文件")
    print("-" * 50)
    
    for i, md_file in enumerate(md_files):
        if update_md_file(md_file, use_ai):
            stats["success"] += 1
        else:
            stats["failed"] += 1
        
        if (i + 1) % 500 == 0:
            print(f"  进度: {i + 1}/{stats['total']} ({100*(i+1)/stats['total']:.1f}%)")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='自动生成表单功能描述和业务场景',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        'directory', 
        nargs='?',
        default='OriginalKnowledgeData/formStructure',
        help='MD 文件目录 (默认: OriginalKnowledgeData/formStructure)'
    )
    parser.add_argument(
        '--ai', 
        action='store_true',
        help='使用 AI 模型生成描述 (需要模型支持)'
    )
    
    args = parser.parse_args()
    
    print(f"处理模式: {'AI 模式' if args.ai else '规则模板模式'}")
    print("-" * 50)
    
    stats = process_directory(args.directory, args.ai)
    
    print("-" * 50)
    print(f"处理完成:")
    print(f"  总计: {stats['total']}")
    print(f"  成功: {stats['success']}")
    print(f"  失败: {stats['failed']}")


if __name__ == '__main__':
    main()

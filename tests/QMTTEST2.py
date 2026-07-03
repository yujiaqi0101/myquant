import requests
import pandas as pd
import json
import re
from typing import Optional

def get_eastmoney_block_flow(
    trade_date: Optional[str] = None,
    block_type: str = "industry"
) -> pd.DataFrame:
    """
    从东方财富网页API获取板块资金流向数据（免费，与东财软件完全一致）
    
    参数:
        trade_date: 交易日期，格式'YYYY-MM-DD'，默认None表示今日
        block_type: 板块类型，'industry'=行业板块，'concept'=概念板块
    
    返回:
        DataFrame: 包含板块名称、代码、各档位资金净流入的数据
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    
    # 板块类型参数
    fs_map = {
        "industry": "m:90+t:2",    # 行业板块
        "concept": "m:90+t:3"      # 概念板块
    }
    
    params = {
        "cb": "jQuery112307879834664846898_1630941013041",
        "fid": "f62",  # 按主力净流入排序
        "po": "1",     # 降序排列
        "pz": "200",   # 每页数量，最多200（覆盖所有板块）
        "pn": "1",     # 页码
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fs": fs_map.get(block_type, "m:90+t:2"),
        "fields": "f12,f14,f62,f63,f64,f65,f66,f67,f69,f3,f124",
        "_": str(int(pd.Timestamp.now().timestamp() * 1000))
    }
    
    # 历史数据需要指定日期
    if trade_date:
        params["dect"] = "1"
        params["date"] = trade_date.replace("-", "")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://data.eastmoney.com/bkzj/hy.html"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        print(response.text)
        response.raise_for_status()
    except Exception as e:
        print(f"请求失败：{str(e)}")
        return pd.DataFrame()
    
    # 解析JSONP格式数据
    json_str = re.sub(r'^jQuery.*?\(', '', response.text)
    json_str = re.sub(r'\)$', '', json_str)
    
    try:
        data = json.loads(json_str)
        print(data)
    except json.JSONDecodeError:
        print("数据解析失败")
        return pd.DataFrame()
    
    if not data.get("data") or not data["data"].get("diff"):
        print("未获取到有效板块资金数据")
        return pd.DataFrame()
    
    # 转换为DataFrame并重命名列
    df = pd.DataFrame(data["data"]["diff"])
    df.columns = [
        "板块代码", "板块名称", "主力净流入(万元)", "主力净流入占比(%)",
        "超大单净流入(万元)", "大单净流入(万元)", "中单净流入(万元)",
        "小单净流入(万元)", "总净流入(万元)", "涨跌幅(%)", "换手率(%)"
    ]
    
    # 转换数值类型
    numeric_cols = [
        "主力净流入(万元)", "主力净流入占比(%)", "超大单净流入(万元)",
        "大单净流入(万元)", "中单净流入(万元)", "小单净流入(万元)",
        "总净流入(万元)", "涨跌幅(%)", "换手率(%)"
    ]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    
    # 标准化板块代码格式（东财内部代码转通用BK格式）
    df["板块代码"] = "BK" + df["板块代码"].astype(str)
    
    return df.sort_values("主力净流入(万元)", ascending=False).reset_index(drop=True)

# 示例使用
if __name__ == "__main__":
    # 1. 获取今日行业板块资金流向TOP10
    print("=== 今日行业板块主力净流入TOP10 ===")
    industry_df = get_eastmoney_block_flow(block_type="industry")
    if not industry_df.empty:
        print(industry_df.head(10).to_string(index=False))
    
    # 2. 获取今日概念板块资金流向TOP10
    print("\n=== 今日概念板块主力净流入TOP10 ===")
    concept_df = get_eastmoney_block_flow(block_type="concept")
    if not concept_df.empty:
        print(concept_df.head(10).to_string(index=False))
    
    # 3. 获取历史日期数据（示例：2026-05-27）
    print("\n=== 2026-05-27 行业板块主力净流入TOP5 ===")
    history_df = get_eastmoney_block_flow(trade_date="2026-05-27", block_type="industry")
    if not history_df.empty:
        print(history_df.head(5).to_string(index=False))
    
    # 4. 保存到CSV文件
    # industry_df.to_csv("东财行业板块资金流向.csv", index=False, encoding="utf-8-sig")
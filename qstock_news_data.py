"""
新闻数据获取模块
使用akshare获取股票的最新新闻信息（替代qstock）
"""

import pandas as pd
import sys
import io
import re
import warnings
from datetime import datetime, timedelta

# 应用 AkShare 请求补丁，减少东方财富 / 财联社接口被拦截的概率
from utils.akshare_helper import patch_requests
patch_requests()

import akshare as ak

warnings.filterwarnings('ignore')

# 设置标准输出编码为UTF-8（仅在命令行环境，避免streamlit冲突）
def _setup_stdout_encoding():
    """仅在命令行环境设置标准输出编码"""
    if sys.platform == 'win32' and not hasattr(sys.stdout, '_original_stream'):
        try:
            # 检测是否在streamlit环境中
            import streamlit
            # 在streamlit中不修改stdout
            return
        except ImportError:
            # 不在streamlit环境，可以安全修改
            try:
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')
            except:
                pass

_setup_stdout_encoding()


class QStockNewsDataFetcher:
    """新闻数据获取类（使用akshare作为数据源）"""
    
    def __init__(self):
        self.max_items = 30  # 最多获取的新闻数量
        self.available = True
        print("✓ 新闻数据获取器初始化成功（akshare数据源）")
    
    def get_stock_news(self, symbol):
        """
        获取股票的新闻数据
        
        Args:
            symbol: 股票代码（6位数字）
            
        Returns:
            dict: 包含新闻数据的字典
        """
        data = {
            "symbol": symbol,
            "news_data": None,
            "data_success": False,
            "source": "akshare"
        }
        
        if not self.available:
            data["error"] = "qstock库未安装或不可用"
            return data
        
        # 只支持中国股票
        if not self._is_chinese_stock(symbol):
            data["error"] = "新闻数据仅支持中国A股股票"
            return data
        
        try:
            # 获取新闻数据
            print(f"📰 正在使用akshare获取 {symbol} 的最新新闻...")
            news_data = self._get_news_data(symbol)
            
            if news_data:
                data["news_data"] = news_data
                print(f"   ✓ 成功获取 {len(news_data.get('items', []))} 条新闻")
                data["data_success"] = True
                print("✅ 新闻数据获取完成")
            else:
                print("⚠️ 未能获取到新闻数据")
                
        except Exception as e:
            print(f"❌ 获取新闻数据失败: {e}")
            data["error"] = str(e)
        
        return data
    
    def _is_chinese_stock(self, symbol):
        """判断是否为中国股票"""
        return symbol.isdigit() and len(symbol) == 6
    
    def _get_news_data(self, symbol):
        """获取新闻数据（使用akshare）"""
        try:
            print(f"   使用 akshare 获取新闻...")
            
            news_items = []
            stock_name = None

            try:
                df_info = ak.stock_zh_a_spot_em()
                if df_info is not None and not df_info.empty:
                    match = df_info[df_info['代码'] == symbol]
                    if not match.empty:
                        stock_name = match.iloc[0]['名称']
                        print(f"   找到股票名称: {stock_name}")
            except Exception as e:
                print(f"   ⚠ 获取股票名称失败: {e}")
            
            # 方法1: 尝试获取个股新闻（东方财富）
            try:
                # stock_news_em(symbol="600519") - 东方财富个股新闻
                df = ak.stock_news_em(symbol=symbol)
                
                if df is not None and not df.empty:
                    print(f"   ✓ 从东方财富获取到 {len(df)} 条新闻")
                    
                    # 处理DataFrame，提取新闻
                    for idx, row in df.head(self.max_items).iterrows():
                        item = {'source': '东方财富'}
                        
                        # 提取所有列
                        for col in df.columns:
                            value = row.get(col)
                            
                            # 跳过空值
                            if value is None or (isinstance(value, float) and pd.isna(value)):
                                continue
                            
                            # 保存字段
                            try:
                                item[col] = str(value)
                            except:
                                item[col] = "无法解析"
                        
                        if len(item) > 1:  # 如果有数据才添加
                            news_items.append(item)
            
            except Exception as e:
                print(f"   ⚠ 从东方财富获取失败: {e}")
            
            # 方法2: 东方财富失败时，先尝试新浪全球快讯
            if not news_items:
                try:
                    df = ak.stock_info_global_sina()
                    if df is not None and not df.empty:
                        print(f"   ✓ 从新浪财经获取到 {len(df)} 条全球快讯")

                        keywords = [symbol]
                        pattern = "|".join(re.escape(keyword) for keyword in keywords if keyword)
                        df_filtered = df

                        if pattern and 'summary' in df.columns:
                            matched = df[df['summary'].astype(str).str.contains(pattern, na=False)]
                            if not matched.empty:
                                df_filtered = matched

                        for idx, row in df_filtered.head(self.max_items).iterrows():
                            item = {'source': '新浪财经'}
                            for col in df_filtered.columns:
                                value = row.get(col)
                                if value is None or (isinstance(value, float) and pd.isna(value)):
                                    continue
                                try:
                                    item[col] = str(value)
                                except:
                                    item[col] = "无法解析"
                            if len(item) > 1:
                                news_items.append(item)
                except Exception as e:
                    print(f"   ⚠ 从新浪财经获取失败: {e}")
            
            # 方法3: 再尝试财联社快讯
            if not news_items or len(news_items) < 5:
                try:
                    # stock_info_global_cls() - 财联社全球快讯
                    df = ak.stock_info_global_cls()
                    
                    if df is not None and not df.empty:
                        keywords = [symbol]
                        if stock_name:
                            keywords.append(stock_name)
                        pattern = "|".join(re.escape(keyword) for keyword in keywords if keyword)

                        df_filtered = df
                        if pattern and '标题' in df.columns and '内容' in df.columns:
                            title_mask = df['标题'].astype(str).str.contains(pattern, na=False)
                            content_mask = df['内容'].astype(str).str.contains(pattern, na=False)
                            matched = df[title_mask | content_mask]
                            if not matched.empty:
                                df_filtered = matched
                        
                        if not df_filtered.empty:
                            print(f"   ✓ 从财联社获取到 {len(df_filtered)} 条相关新闻")
                            
                            for idx, row in df_filtered.head(self.max_items - len(news_items)).iterrows():
                                item = {'source': '财联社'}
                                
                                for col in df_filtered.columns:
                                    value = row.get(col)
                                    if value is None or (isinstance(value, float) and pd.isna(value)):
                                        continue
                                    try:
                                        item[col] = str(value)
                                    except:
                                        item[col] = "无法解析"
                                
                                if len(item) > 1:
                                    news_items.append(item)
                
                except Exception as e:
                    print(f"   ⚠ 从财联社获取失败: {e}")

            # 方法4: 财新快讯作为最后兜底
            if not news_items:
                try:
                    df = ak.stock_news_main_cx()
                    if df is not None and not df.empty:
                        print(f"   ✓ 从财新获取到 {len(df)} 条财经精选")
                        for idx, row in df.head(self.max_items).iterrows():
                            item = {'source': '财新'}
                            for col in df.columns:
                                value = row.get(col)
                                if value is None or (isinstance(value, float) and pd.isna(value)):
                                    continue
                                try:
                                    item[col] = str(value)
                                except:
                                    item[col] = "无法解析"
                            if len(item) > 1:
                                news_items.append(item)
                except Exception as e:
                    print(f"   ⚠ 从财新获取失败: {e}")
            
            if not news_items:
                print(f"   未找到股票 {symbol} 的新闻")
                return None
            
            # 限制数量
            news_items = news_items[:self.max_items]
            
            return {
                "items": news_items,
                "count": len(news_items),
                "query_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "date_range": "最近新闻"
            }
            
        except Exception as e:
            print(f"   获取新闻数据异常: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def format_news_for_ai(self, data):
        """
        将新闻数据格式化为适合AI阅读的文本
        """
        if not data or not data.get("data_success"):
            return "未能获取新闻数据"
        
        text_parts = []
        
        # 新闻数据
        if data.get("news_data"):
            news_data = data["news_data"]
            text_parts.append(f"""
【最新新闻 - akshare数据源】
查询时间：{news_data.get('query_time', 'N/A')}
时间范围：{news_data.get('date_range', 'N/A')}
新闻数量：{news_data.get('count', 0)}条

""")
            
            for idx, item in enumerate(news_data.get('items', []), 1):
                text_parts.append(f"新闻 {idx}:")

                def _first_value(keys):
                    for key in keys:
                        value = item.get(key)
                        if value not in (None, "", "N/A"):
                            return value
                    return None

                title = _first_value(['title', '标题', '新闻标题'])
                date = _first_value(['date', '日期', '发布时间', '发布日期', 'time', '时间'])
                source = _first_value(['source', '来源'])
                content = _first_value(['content', '内容', '新闻内容'])
                url = _first_value(['url', '链接', '新闻链接'])

                if title:
                    text_parts.append(f"  标题: {title}")
                if date:
                    text_parts.append(f"  时间: {date}")
                if source:
                    text_parts.append(f"  来源: {source}")
                if content:
                    content_text = str(content)
                    if len(content_text) > 500:
                        content_text = content_text[:500] + "..."
                    text_parts.append(f"  内容: {content_text}")
                if url:
                    text_parts.append(f"  链接: {url}")
                
                text_parts.append("")  # 空行分隔
        
        return "\n".join(text_parts)


# 测试函数
if __name__ == "__main__":
    print("测试新闻数据获取（akshare数据源）...")
    print("="*60)
    
    fetcher = QStockNewsDataFetcher()
    
    if not fetcher.available:
        print("❌ 新闻数据获取器不可用")
        sys.exit(1)
    
    # 测试股票
    test_symbols = ["000001", "600519"]  # 平安银行、贵州茅台
    
    for symbol in test_symbols:
        print(f"\n{'='*60}")
        print(f"正在测试股票: {symbol}")
        print(f"{'='*60}\n")
        
        data = fetcher.get_stock_news(symbol)
        
        if data.get("data_success"):
            print("\n" + "="*60)
            print("新闻数据获取成功！")
            print("="*60)
            
            formatted_text = fetcher.format_news_for_ai(data)
            print(formatted_text)
        else:
            print(f"\n获取失败: {data.get('error', '未知错误')}")
        
        print("\n")

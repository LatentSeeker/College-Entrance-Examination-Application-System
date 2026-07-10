"""
高校2025年专业组分数线爬虫 - Playwright版本
从 https://www.gaokao.cn/school/{id}/provinceline 抓取数据
支持JavaScript渲染的页面
"""

import json
import csv
import time
import os
from datetime import datetime
import asyncio
from playwright.async_api import async_playwright

class GaokaoScraper:
    def __init__(self):
        self.output_dir = 'output'
        os.makedirs(self.output_dir, exist_ok=True)
        
    async def scrape_school(self, page, school_id):
        """抓取单个学校的分数线数据"""
        url = f"https://www.gaokao.cn/school/{school_id}/provinceline?fromcoop=bdkp"
        print(f"\n正在抓取: ID {school_id}")
        print(f"URL: {url}")
        
        try:
            # 导航到页面
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)  # 额外等待数据加载
            
            # 获取学校名称
            school_name = await page.evaluate('''() => {
                const h1 = document.querySelector('h1');
                const h2 = document.querySelector('h2');
                const nameEl = document.querySelector('[class*="name"]');
                return (h1 || h2 || nameEl)?.textContent?.trim() || '未知';
            }''')
            
            print(f"学校: {school_name}")
            
            # 尝试获取表格数据
            table_data = await page.evaluate('''() => {
                // 查找表格
                const tables = document.querySelectorAll('table');
                if (tables.length === 0) {
                    // 尝试查找包含分数线的div
                    const scoreDivs = document.querySelectorAll('[class*="score"], [class*="line"], [class*="data"]');
                    if (scoreDivs.length > 0) {
                        return {
                            type: 'divs',
                            count: scoreDivs.length,
                            html: scoreDivs[0].innerHTML.substring(0, 500)
                        };
                    }
                }
                
                // 获取表格内容
                const rows = [];
                tables.forEach(table => {
                    const trs = table.querySelectorAll('tr');
                    trs.forEach(tr => {
                        const cells = tr.querySelectorAll('td, th');
                        const rowData = [];
                        cells.forEach(cell => {
                            rowData.push(cell.textContent.trim());
                        });
                        if (rowData.length > 0) {
                            rows.push(rowData);
                        }
                    });
                });
                
                return {
                    type: 'table',
                    rows: rows
                };
            }''')
            
            # 获取页面中的所有文本（备用）
            if not table_data or (table_data.get('type') == 'divs' and table_data.get('count', 0) == 0):
                all_text = await page.evaluate('''() => {
                    return document.body.innerText;
                }''')
                
                # 查找包含"专业组"、"分数线"等关键词的内容
                lines = all_text.split('\n')
                relevant_lines = [line.strip() for line in lines if 
                                 '专业组' in line or '分数线' in line or 
                                 '最低分' in line or '投档' in line]
                
                table_data = {
                    type: 'text',
                    relevant_lines: relevant_lines[:50]  # 最多50行
                }
            
            return {
                'school_id': school_id,
                'school_name': school_name,
                'data': table_data,
                'url': url,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"✗ 抓取失败: {str(e)}")
            return {
                'school_id': school_id,
                'error': str(e),
                'url': url
            }
    
    async def scrape_multiple_schools(self, start_id=1, end_id=50, headless=True):
        """批量抓取多个学校"""
        print(f"开始批量抓取: ID {start_id} - {end_id}")
        print(f"无头模式: {headless}")
        
        results = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            for school_id in range(start_id, end_id + 1):
                result = await self.scrape_school(page, school_id)
                results.append(result)
                
                if 'error' not in result:
                    print(f"✓ 成功: {result.get('school_name', '未知')}")
                else:
                    print(f"✗ 失败: ID {school_id}")
                
                # 延迟避免被封
                await asyncio.sleep(1)
                
                # 每10个保存一次进度
                if len(results) % 10 == 0:
                    self.save_results(results, f'progress_{start_id}_{school_id}')
                    print(f"\n[进度保存] 已保存 {len(results)} 条")
            
            await browser.close()
        
        return results
    
    def save_results(self, results, filename_prefix='高校分数线'):
        """保存结果到文件"""
        if not results:
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存JSON
        json_path = os.path.join(self.output_dir, f'{filename_prefix}_{timestamp}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON已保存: {json_path}")
        
        # 保存简化的CSV
        csv_path = os.path.join(self.output_dir, f'{filename_prefix}_{timestamp}.csv')
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['学校ID', '学校名称', '数据类型', '数据摘要', 'URL'])
            
            for result in results:
                school_id = result.get('school_id', '')
                school_name = result.get('school_name', '')
                url = result.get('url', '')
                
                data = result.get('data', {})
                data_type = data.get('type', 'unknown') if isinstance(data, dict) else 'unknown'
                
                # 数据摘要
                if data_type == 'table':
                    rows = data.get('rows', [])
                    data_summary = f"表格: {len(rows)}行"
                elif data_type == 'divs':
                    data_summary = f"数据块: {data.get('count', 0)}个"
                elif data_type == 'text':
                    lines = data.get('relevant_lines', [])
                    data_summary = f"相关文本: {len(lines)}行"
                else:
                    data_summary = '无数据'
                
                writer.writerow([school_id, school_name, data_type, data_summary, url])
        
        print(f"CSV已保存: {csv_path}")
        print(f"共保存 {len(results)} 条记录")


async def main():
    print("=" * 70)
    print("高考分数线数据爬虫 - Playwright版")
    print("=" * 70)
    print("\n此脚本将抓取高校2025年专业组分数线数据")
    print("数据源: https://www.gaokao.cn/school/{id}/provinceline\n")
    
    scraper = GaokaoScraper()
    
    try:
        # 先测试单个学校
        print("【测试阶段】抓取学校ID=1的数据...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            test_result = await scraper.scrape_school(page, 1)
            
            if test_result and 'error' not in test_result:
                print("\n✓ 测试成功! 数据结构:")
                print(json.dumps(test_result['data'], ensure_ascii=False, indent=2)[:500])
                
                answer = input("\n是否开始批量抓取? (y/n): ").strip().lower()
                
                if answer == 'y':
                    await browser.close()
                    
                    # 批量抓取
                    print("\n【批量抓取阶段】")
                    start_id = 30
                    end_id = input("请输入结束ID (默认50): ").strip()
                    end_id = int(end_id) if end_id else 50
                    
                    results = await scraper.scrape_multiple_schools(
                        start_id, end_id, headless=True
                    )
                    
                    # 保存最终结果
                    scraper.save_results(results)
                    print(f"\n✓ 完成! 共抓取 {len(results)} 所学校")
                else:
                    # 保存测试结果
                    scraper.save_results([test_result], 'test_result')
                    await browser.close()
            else:
                print("\n✗ 测试失败")
                print("错误信息:", test_result.get('error', '未知错误'))
                await browser.close()
                
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n程序错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

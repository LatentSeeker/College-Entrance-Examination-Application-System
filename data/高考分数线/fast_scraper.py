"""
高校2025年专业组分数线爬虫 - 高速并发版
使用多浏览器实例并发抓取，速度提升3-5倍
"""

import json
import csv
import time
import os
from datetime import datetime
import asyncio
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor
import threading

class FastGaokaoScraper:
    def __init__(self, max_workers=3):
        """
        初始化爬虫
        max_workers: 并发数，建议3-5个，太多可能被封
        """
        self.output_dir = 'output'
        os.makedirs(self.output_dir, exist_ok=True)
        self.results = []
        self.results_lock = threading.Lock()
        self.max_workers = max_workers
        self.success_count = 0
        self.fail_count = 0
        self.saved_count = 0  # 记录已保存的数量
        
    async def scrape_school(self, page, school_id):
        """抓取单个学校的分数线数据"""
        url = f"https://www.gaokao.cn/school/{school_id}/provinceline?fromcoop=bdkp"
        
        try:
            # 减少等待时间
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(1500)  # 减少等待时间从3秒到1.5秒
            
            # 获取学校名称
            school_name = await page.evaluate('''() => {
                const h1 = document.querySelector('h1');
                const h2 = document.querySelector('h2');
                const nameEl = document.querySelector('[class*="name"]');
                return (h1 || h2 || nameEl)?.textContent?.trim() || '未知';
            }''')
            
            # 获取表格数据
            table_data = await page.evaluate('''() => {
                const tables = document.querySelectorAll('table');
                if (tables.length === 0) {
                    const scoreDivs = document.querySelectorAll('[class*="score"], [class*="line"], [class*="data"]');
                    if (scoreDivs.length > 0) {
                        return {
                            type: 'divs',
                            count: scoreDivs.length
                        };
                    }
                }
                
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
            
            return {
                'school_id': school_id,
                'school_name': school_name,
                'data': table_data,
                'url': url,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'school_id': school_id,
                'error': str(e),
                'url': url
            }
    
    async def worker(self, worker_id, browser, school_ids):
        """工作协程，处理一批学校ID"""
        print(f"[Worker {worker_id}] 开始处理 {len(school_ids)} 所学校")
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        for school_id in school_ids:
            result = await self.scrape_school(page, school_id)
            
            with self.results_lock:
                self.results.append(result)
                
                if 'error' not in result:
                    self.success_count += 1
                    name = result.get('school_name', '未知')
                    print(f"[Worker {worker_id}] 成功: ID {school_id} - {name}")
                else:
                    self.fail_count += 1
                    print(f"[Worker {worker_id}] 失败: ID {school_id}")
                
                # 每20个保存一次进度（减少保存频率）
                total = len(self.results)
                if total - self.saved_count >= 20:
                    self.save_progress()
                    self.saved_count = total
                    print(f"[Worker {worker_id}] 进度保存: {total} 条\n")
            
            # 减少延迟到0.5秒
            await asyncio.sleep(0.5)
        
        await context.close()
        print(f"[Worker {worker_id}] 完成")
    
    async def scrape_range_fast(self, start_id, end_id):
        """高速并发抓取"""
        print(f"开始高速并发抓取: ID {start_id} - {end_id}")
        print(f"并发数: {self.max_workers}")
        
        # 将学校ID分配给多个worker
        all_ids = list(range(start_id, end_id + 1))
        chunks = [[] for _ in range(self.max_workers)]
        
        for i, school_id in enumerate(all_ids):
            chunks[i % self.max_workers].append(school_id)
        
        print(f"总共 {len(all_ids)} 所学校，分配给 {self.max_workers} 个worker\n")
        
        async with async_playwright() as p:
            # 启动多个浏览器实例
            browsers = []
            for i in range(self.max_workers):
                browser = await p.chromium.launch(headless=True)
                browsers.append(browser)
            
            # 并发执行
            tasks = []
            for i, (browser, chunk) in enumerate(zip(browsers, chunks)):
                if chunk:
                    task = asyncio.create_task(self.worker(i+1, browser, chunk))
                    tasks.append(task)
            
            # 等待所有任务完成
            await asyncio.gather(*tasks)
            
            # 关闭所有浏览器
            for browser in browsers:
                await browser.close()
        
        print(f"\n抓取完成!")
        print(f"成功: {self.success_count}, 失败: {self.fail_count}")
        
        return self.results
    
    def save_progress(self):
        """保存进度 - 使用单一文件覆盖更新"""
        # 使用固定文件名，每次覆盖，避免产生大量重复文件
        filepath = os.path.join(self.output_dir, 'fast_progress_latest.json')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
    
    def save_final_results(self, filename_prefix='高校分数线_高速版'):
        """保存最终结果"""
        if not self.results:
            print("没有数据可保存")
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存JSON
        json_path = os.path.join(self.output_dir, f'{filename_prefix}_{timestamp}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        print(f"JSON已保存: {json_path}")
        
        # 保存简化的CSV
        csv_path = os.path.join(self.output_dir, f'{filename_prefix}_{timestamp}.csv')
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['学校ID', '学校名称', '数据类型', '数据摘要', 'URL'])
            
            for result in self.results:
                school_id = result.get('school_id', '')
                school_name = result.get('school_name', '')
                url = result.get('url', '')
                
                data = result.get('data', {})
                data_type = data.get('type', 'unknown') if isinstance(data, dict) else 'unknown'
                
                if data_type == 'table':
                    rows = data.get('rows', [])
                    data_summary = f"表格: {len(rows)}行"
                elif data_type == 'divs':
                    data_summary = f"数据块: {data.get('count', 0)}个"
                else:
                    data_summary = '无数据'
                
                writer.writerow([school_id, school_name, data_type, data_summary, url])
        
        print(f"CSV已保存: {csv_path}")
        print(f"共保存 {len(self.results)} 条记录")


async def main():
    print("=" * 70)
    print("高考分数线数据爬虫 - 高速并发版")
    print("=" * 70)
    print("\n优化项:")
    print("1. 3个浏览器实例并发抓取")
    print("2. 减少页面等待时间")
    print("3. 减少请求间隔")
    print("预计速度提升: 3-5倍\n")
    
    # 设置参数
    print("请输入抓取范围:")
    start_input = input("起始ID (默认329): ").strip()
    start_id = int(start_input) if start_input else 329
    
    end_input = input("结束ID (默认500): ").strip()
    end_id = int(end_input) if end_input else 500
    
    workers_input = input("并发数 (默认3, 建议2-5): ").strip()
    max_workers = int(workers_input) if workers_input else 3
    
    print(f"\n确认配置:")
    print(f"抓取范围: ID {start_id} - {end_id}")
    print(f"并发数: {max_workers}")
    print(f"预计时间: 约{(end_id - start_id + 1) * 0.5 / max_workers:.0f}秒\n")
    
    confirm = input("开始抓取? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    scraper = FastGaokaoScraper(max_workers=max_workers)
    
    try:
        results = await scraper.scrape_range_fast(start_id, end_id)
        
        if results:
            scraper.save_final_results()
            
            print(f"\n抓取统计:")
            print(f"总计: {len(results)} 所学校")
            print(f"成功: {scraper.success_count}")
            print(f"失败: {scraper.fail_count}")
            
            print(f"\n下一步:")
            print(f"1. 运行 convert_to_csv.py 转换为完整CSV")
            print(f"2. 查看 output/ 目录下的数据文件")
        else:
            print("\n未获取到任何数据")
            
    except KeyboardInterrupt:
        print("\n\n用户中断，正在保存已获取的数据...")
        scraper.save_final_results('interrupted')
    except Exception as e:
        print(f"\n程序错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n完成!")


if __name__ == "__main__":
    asyncio.run(main())

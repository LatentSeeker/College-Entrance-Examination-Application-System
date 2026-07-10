# 高考分数线数据爬虫

这个工具用于从高考网(https://www.gaokao.cn)抓取各个高校2025年各专业组的分数线数据。

## 安装步骤

### 1. 安装Playwright

```bash
pip install playwright
playwright install chromium
```

### 2. 运行爬虫

```bash
python gaokao_scraper.py
```

## 使用说明

### 快速开始

1. 运行脚本后，会先测试抓取学校ID=1的数据
2. 如果测试成功，会询问是否开始批量抓取
3. 输入要抓取的结束ID（默认50）
4. 等待抓取完成，数据会自动保存到`output`目录

### 数据格式

抓取的数据会保存为两种格式：

- **JSON格式**: 包含完整的原始数据
- **CSV格式**: 包含简化的摘要信息

### 文件位置

所有数据保存在 `output/` 目录下：
- `output/高校分数线_YYYYMMDD_HHMMSS.json`
- `output/高校分数线_YYYYMMDD_HHMMSS.csv`

## 自定义抓取

如果需要抓取特定范围的学校，可以修改脚本：

```python
# 在 main() 函数中修改
results = await scraper.scrape_multiple_schools(
    start_id=1,    # 起始ID
    end_id=100,    # 结束ID
    headless=True  # True=后台运行, False=显示浏览器
)
```

## 学校ID说明

- 每个学校有一个唯一的数字ID
- ID=1 代表清华大学
- ID=2 代表北京大学
- 以此类推...

你可以在浏览器中访问 `https://www.gaokao.cn/school/{ID}/provinceline` 来查看特定学校的数据

## 注意事项

1. **请求频率**: 脚本每次请求间隔1秒，避免被封IP
2. **数据完整性**: 不是所有学校都有2025年的专业组分数线数据
3. **浏览器**: 需要安装Chromium浏览器（通过`playwright install chromium`）
4. **网络**: 需要稳定的网络连接

## 故障排除

### 问题1: 无法安装playwright

```bash
# 使用国内镜像
pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 问题2: Chromium下载失败

```bash
# 手动下载或设置镜像
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors
playwright install chromium
```

### 问题3: 抓取不到数据

- 检查网络连接
- 尝试设置 `headless=False` 查看浏览器行为
- 确认目标学校确实有分数线数据

## 数据示例

成功抓取后，JSON数据格式如下：

```json
[
  {
    "school_id": 1,
    "school_name": "清华大学",
    "data": {
      "type": "table",
      "rows": [
        ["专业组", "最低分", "最低位次", "批次"],
        ["01", "680", "100", "本科批"],
        ...
      ]
    },
    "url": "https://www.gaokao.cn/school/1/provinceline?fromcoop=bdkp",
    "timestamp": "2026-06-24T10:30:00"
  }
]
```

## 许可

本工具仅用于学习和研究目的。

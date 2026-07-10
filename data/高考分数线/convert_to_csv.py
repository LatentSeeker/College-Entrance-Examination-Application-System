"""
将抓取的JSON数据转换为完整的CSV格式
提取所有专业组和专业的详细分数线
"""

import json
import csv
import os
from datetime import datetime

def convert_json_to_csv(json_file, output_file=None):
    """将JSON数据转换为完整的CSV格式"""
    
    # 读取JSON数据
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f'output/高校分数线完整数据_{timestamp}.csv'
    
    # 创建输出目录
    os.makedirs('output', exist_ok=True)
    
    # 写入CSV
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        
        # 写入表头
        writer.writerow([
            '学校ID',
            '学校名称',
            '年份',
            '录取批次',
            '招生类型',
            '专业组',
            '选科要求',
            '最低分',
            '最低位次',
            '专业名称',
            '专业最低分',
            '专业最低位次',
            '数据来源URL'
        ])
        
        total_rows = 0
        school_count = 0
        
        # 处理每个学校的数据
        for school in data:
            school_id = school.get('school_id', '')
            school_name = school.get('school_name', '')
            url = school.get('url', '')
            
            if not school_name:
                continue
            
            school_count += 1
            data_content = school.get('data', {})
            
            if data_content.get('type') != 'table':
                continue
            
            rows = data_content.get('rows', [])
            if not rows:
                continue
            
            # 判断是专业组数据还是专业数据
            # 专业组数据：年份|录取批次|招生类型|专业组/选科要求|最低分/最低位次|录取率
            # 专业数据：专业名称|最低分/最低位次|录取率
            
            in_major_section = False  # 是否在专业数据区域
            
            for row in rows:
                if len(row) < 3:
                    continue
                
                # 检测是否是专业数据的表头
                if row[0] == '专业名称':
                    in_major_section = True
                    continue
                
                # 跳过表头
                if row[0] == '年份':
                    in_major_section = False
                    continue
                
                if in_major_section:
                    # 专业数据行
                    # 格式：专业名称（包含选科要求）|最低分/最低位次|录取率
                    major_name_full = row[0] if len(row) > 0 else ''
                    score_rank = row[1] if len(row) > 1 else ''
                    
                    # 分离专业名称和选科要求
                    if '选科要求：' in major_name_full:
                        parts = major_name_full.split('选科要求：')
                        major_name = parts[0].strip()
                        subject_req = parts[1].strip() if len(parts) > 1 else ''
                    else:
                        major_name = major_name_full
                        subject_req = ''
                    
                    # 分离分数和位次
                    if '/' in score_rank:
                        score, rank = score_rank.split('/')
                        score = score.strip()
                        rank = rank.strip()
                    else:
                        score = score_rank
                        rank = ''
                    
                    writer.writerow([
                        school_id,
                        school_name,
                        '',  # 年份
                        '',  # 录取批次
                        '',  # 招生类型
                        '',  # 专业组
                        subject_req,
                        '',  # 专业组最低分
                        '',  # 专业组最低位次
                        major_name,
                        score,
                        rank,
                        url
                    ])
                    total_rows += 1
                    
                else:
                    # 专业组数据行
                    # 格式：年份|录取批次|招生类型|专业组/选科要求|最低分/最低位次|录取率
                    year = row[0] if len(row) > 0 else ''
                    batch = row[1] if len(row) > 1 else ''
                    admit_type = row[2] if len(row) > 2 else ''
                    group_subject = row[3] if len(row) > 3 else ''
                    score_rank = row[4] if len(row) > 4 else ''
                    
                    # 分离专业组和选科要求
                    if '）' in group_subject:
                        # 格式：专业组（501）首选物理，再选化学
                        idx = group_subject.index('）')
                        group = group_subject[:idx+1].strip()
                        subject_req = group_subject[idx+1:].strip()
                    else:
                        group = group_subject
                        subject_req = ''
                    
                    # 分离分数和位次
                    if '/' in score_rank:
                        score, rank = score_rank.split('/')
                        score = score.strip()
                        rank = rank.strip()
                    else:
                        score = score_rank
                        rank = ''
                    
                    writer.writerow([
                        school_id,
                        school_name,
                        year,
                        batch,
                        admit_type,
                        group,
                        subject_req,
                        score,
                        rank,
                        '',  # 专业名称
                        '',  # 专业最低分
                        '',  # 专业最低位次
                        url
                    ])
                    total_rows += 1
        
        print("转换完成!")
        print(f"处理学校数: {school_count}")
        print(f"总数据行数: {total_rows}")
        print(f"保存文件: {output_file}")
        
        return output_file


def main():
    print("=" * 60)
    print("高考分数线数据转换器")
    print("=" * 60)
    
    # 查找最新的JSON文件
    output_dir = 'output'
    if not os.path.exists(output_dir):
        print("错误: output目录不存在")
        return
    
    json_files = [f for f in os.listdir(output_dir) if f.endswith('.json')]
    if not json_files:
        print("错误: 没有找到JSON文件")
        return
    
    # 按时间排序，使用最新的文件
    json_files.sort(reverse=True)
    latest_json = os.path.join(output_dir, json_files[0])
    
    print(f"\n找到JSON文件: {latest_json}")
    
    # 转换
    output_file = convert_json_to_csv(latest_json)
    
    print(f"\n完成! 可以在Excel中打开: {output_file}")


if __name__ == "__main__":
    main()

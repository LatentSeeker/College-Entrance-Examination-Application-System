"""
高考分数线数据提取脚本
从抓取的JSON文件中提取：
- 学校名称（截断"大学"、"学院"、"学校"之前的部分）
- 学校地区（从school_name字段提取）
- 各专业组及各专业的最低分和最低位次
- 学校整体最低分和最低排名（所有专业中的最低值）

输出格式：每个学校包含多个专业，带有专业分数和学校整体最低分
"""

import json
import os
import re
from datetime import datetime

def extract_school_name_and_region(school_name_full):
    """
    从完整的学校名称中提取学校名和地区
    例如："北京大学北京海淀区" -> ("北京", "大学")
         "北京工业大学北京朝阳区" -> ("北京工业", "大学")
    """
    if not school_name_full or school_name_full == '未知':
        return '', ''
    
    # 匹配模式：学校名称 + 地区
    # 常见的学校类型后缀
    school_types = ['大学', '学院', '学校']
    
    region = ''
    school_name = school_name_full
    
    # 尝试提取地区信息（通常是最后的部分）
    # 匹配常见的地区模式：省份+城市+区县
    region_pattern = r'(北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆)(省|市|自治区|壮族自治区|维吾尔自治区|自治区|特别行政区)?([^\s]+?[市|区|县|州|盟])?'
    
    # 从后往前找地区
    for school_type in school_types:
        if school_type in school_name_full:
            # 找到学校类型的位置
            type_idx = school_name_full.index(school_type)
            
            # 学校类型之后的内容就是地区
            region_part = school_name_full[type_idx + len(school_type):]
            
            if region_part:
                school_name = school_name_full[:type_idx + len(school_type)]
                region = region_part
            else:
                school_name = school_name_full
            
            break
    
    return school_name, region


def parse_score_rank(score_rank_str):
    """
    解析分数和位次字符串
    例如："587/13605" -> (587, 13605)
    """
    if not score_rank_str or score_rank_str == '录取率':
        return None, None
    
    if '/' in score_rank_str:
        parts = score_rank_str.split('/')
        try:
            score = int(parts[0].strip())
            rank = int(parts[1].strip())
            return score, rank
        except:
            return None, None
    else:
        try:
            score = int(score_rank_str.strip())
            return score, None
        except:
            return None, None


def extract_majors_from_group(group_text):
    """
    从专业组文本中提取专业名称
    处理格式如："理科试验班类（元培）（数学类、物理学类、地球物理学类、计算机类、电子信息类）"
    """
    if not group_text:
        return []
    
    # 如果包含顿号，说明有多个专业
    if '、' in group_text:
        # 提取括号内的专业列表
        bracket_match = re.search(r'（(.+?)）', group_text)
        if bracket_match:
            majors_str = bracket_match.group(1)
            if '、' in majors_str:
                return [m.strip() for m in majors_str.split('、')]
    
    return [group_text]


def process_single_school(school_data):
    """
    处理单个学校的数据
    返回结构化数据
    """
    school_id = school_data.get('school_id', '')
    school_name_full = school_data.get('school_name', '')
    
    # 过滤掉无效数据
    if not school_name_full or school_name_full == '高考小智' or school_name_full == '未知':
        return None
    
    # 提取学校名称和地区
    school_name, region = extract_school_name_and_region(school_name_full)
    
    if not school_name:
        return None
    
    data_content = school_data.get('data', {})
    if data_content.get('type') != 'table':
        return None
    
    rows = data_content.get('rows', [])
    if not rows:
        return None
    
    # 数据结构
    result = {
        '学校名称': school_name,
        '地区': region,
        '专业组': [],
        '学校最低分': None,
        '学校最低位次': None
    }
    
    all_scores = []
    all_ranks = []
    
    in_major_section = False
    current_group = None
    
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
                major_name = major_name_full.split('选科要求：')[0].strip()
            else:
                major_name = major_name_full
            
            score, rank = parse_score_rank(score_rank)
            
            if score is not None:
                all_scores.append(score)
            if rank is not None:
                all_ranks.append(rank)
            
            # 如果当前专业组存在，添加专业
            if current_group:
                current_group['专业列表'].append({
                    '专业名称': major_name,
                    '最低分': score,
                    '最低位次': rank
                })
        
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
                idx = group_subject.index('）')
                group_name = group_subject[:idx+1].strip()
                subject_req = group_subject[idx+1:].strip()
            else:
                group_name = group_subject
                subject_req = ''
            
            score, rank = parse_score_rank(score_rank)
            
            if score is not None:
                all_scores.append(score)
            if rank is not None:
                all_ranks.append(rank)
            
            current_group = {
                '年份': year,
                '录取批次': batch,
                '招生类型': admit_type,
                '专业组名称': group_name,
                '选科要求': subject_req,
                '最低分': score,
                '最低位次': rank,
                '专业列表': []
            }
            
            result['专业组'].append(current_group)
    
    # 计算学校整体最低分和最低位次
    if all_scores:
        result['学校最低分'] = min(all_scores)
    if all_ranks:
        result['学校最低位次'] = min(all_ranks)
    
    return result


def process_json_file(json_file):
    """
    处理单个JSON文件
    """
    print(f"处理文件: {json_file}")
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    results = []
    success_count = 0
    fail_count = 0
    
    for school_data in data:
        result = process_single_school(school_data)
        if result:
            results.append(result)
            success_count += 1
        else:
            fail_count += 1
    
    print(f"  成功: {success_count}, 失败: {fail_count}")
    
    return results


def save_to_json(results, output_file):
    """保存为JSON格式"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"JSON已保存: {output_file}")


def save_to_csv(results, output_file):
    """保存为CSV格式（扁平化）"""
    import csv
    
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        
        # 写入表头
        writer.writerow([
            '学校名称',
            '地区',
            '专业组名称',
            '选科要求',
            '年份',
            '录取批次',
            '招生类型',
            '专业组最低分',
            '专业组最低位次',
            '专业名称',
            '专业最低分',
            '专业最低位次',
            '学校最低分',
            '学校最低位次'
        ])
        
        for school in results:
            for group in school['专业组']:
                if group['专业列表']:
                    # 有专业列表
                    for major in group['专业列表']:
                        writer.writerow([
                            school['学校名称'],
                            school['地区'],
                            group['专业组名称'],
                            group['选科要求'],
                            group['年份'],
                            group['录取批次'],
                            group['招生类型'],
                            group['最低分'],
                            group['最低位次'],
                            major['专业名称'],
                            major['最低分'],
                            major['最低位次'],
                            school['学校最低分'],
                            school['学校最低位次']
                        ])
                else:
                    # 没有专业列表，只写入专业组信息
                    writer.writerow([
                        school['学校名称'],
                        school['地区'],
                        group['专业组名称'],
                        group['选科要求'],
                        group['年份'],
                        group['录取批次'],
                        group['招生类型'],
                        group['最低分'],
                        group['最低位次'],
                        '',
                        '',
                        '',
                        school['学校最低分'],
                        school['学校最低位次']
                    ])
    
    print(f"CSV已保存: {output_file}")


def process_multiple_files(input_files, output_dir='output'):
    """
    处理多个JSON文件
    """
    os.makedirs(output_dir, exist_ok=True)
    
    all_results = []
    
    for json_file in input_files:
        if not os.path.exists(json_file):
            print(f"文件不存在: {json_file}")
            continue
        
        results = process_json_file(json_file)
        all_results.extend(results)
    
    if not all_results:
        print("没有数据可保存")
        return
    
    print(f"\n总共处理了 {len(all_results)} 所学校")
    
    # 保存文件
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 保存JSON
    json_output = os.path.join(output_dir, f'高校分数线提取数据_{timestamp}.json')
    save_to_json(all_results, json_output)
    
    # 保存CSV
    csv_output = os.path.join(output_dir, f'高校分数线提取数据_{timestamp}.csv')
    save_to_csv(all_results, csv_output)
    
    return all_results


def main():
    print("=" * 70)
    print("高考分数线数据提取工具")
    print("=" * 70)
    print("\n此脚本将从抓取的JSON文件中提取：")
    print("- 学校名称（截断地区信息）")
    print("- 学校地区")
    print("- 各专业组及各专业的最低分和最低位次")
    print("- 学校整体最低分和最低排名\n")
    
    # 查找output目录下所有的JSON文件
    output_dir = 'output'
    if not os.path.exists(output_dir):
        print(f"错误: {output_dir} 目录不存在")
        return
    
    json_files = []
    for f in os.listdir(output_dir):
        if f.endswith('.json') and not f.startswith('fast_progress'):
            json_files.append(os.path.join(output_dir, f))
    
    if not json_files:
        print("没有找到JSON文件")
        return
    
    print(f"找到 {len(json_files)} 个JSON文件:")
    for i, f in enumerate(json_files, 1):
        print(f"  {i}. {os.path.basename(f)}")
    
    print("\n请选择要处理的文件:")
    print("1. 处理所有文件")
    print("2. 手动选择文件")
    
    choice = input("\n请选择 (1/2, 默认1): ").strip()
    
    if choice == '2':
        indices = input("输入文件编号，用逗号分隔 (如: 1,3,5): ").strip()
        selected_indices = [int(x.strip()) - 1 for x in indices.split(',') if x.strip()]
        selected_files = [json_files[i] for i in selected_indices if 0 <= i < len(json_files)]
    else:
        selected_files = json_files
    
    if not selected_files:
        print("没有选择任何文件")
        return
    
    print(f"\n开始处理 {len(selected_files)} 个文件...\n")
    
    results = process_multiple_files(selected_files)
    
    if results:
        print(f"\n完成! 共提取 {len(results)} 所学校的数据")
        print("文件已保存到 output/ 目录")
        
        # 显示统计信息
        total_groups = sum(len(s['专业组']) for s in results)
        total_majors = sum(
            sum(len(g['专业列表']) for g in s['专业组'])
            for s in results
        )
        
        print(f"\n数据统计:")
        print(f"  学校数: {len(results)}")
        print(f"  专业组数: {total_groups}")
        print(f"  专业数: {total_majors}")


if __name__ == "__main__":
    main()

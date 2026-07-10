import os
import json
import pandas as pd

def extract_school_min_score(folder_path: str, output_file: str = "院校最低投档分汇总.xlsx"):
    """
    按院校汇总：每所大学一行，提取该校所有专业中的最低分、对应最低位次
    自动过滤名称为「高考小智」的错误数据
    """
    result_list = []

    for filename in os.listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        
        file_path = os.path.join(folder_path, filename)
        print(f"正在解析：{filename}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                school_list = json.load(f)
        except Exception as e:
            print(f"读取文件 {filename} 失败：{e}，跳过")
            continue

        for school in school_list:
            # 1. 跳过抓取超时/失败的条目
            if "error" in school:
                print(f"跳过院校ID {school.get('school_id')}：数据抓取失败")
                continue

            school_name = school.get("school_name", "").strip()
            
            # 2. 新增：过滤名称为「高考小智」的错误数据
            if school_name == "高考小智":
                print("跳过错误数据：院校名称为「高考小智」")
                continue

            rows = school.get("data", {}).get("rows", [])
            if not rows or not school_name:
                continue

            # 定位专业分数线表头
            major_header_idx = None
            for idx, row in enumerate(rows):
                if len(row) >= 1 and row[0] == "专业名称":
                    major_header_idx = idx
                    break
            if major_header_idx is None:
                continue

            # 收集该院校所有有效专业的分数、位次、专业名
            major_scores = []
            for row in rows[major_header_idx + 1:]:
                if len(row) < 2:
                    continue
                
                major_full = row[0]
                score_rank_text = row[1]

                # 拆分数和位次
                if "/" not in score_rank_text:
                    continue
                score_str, rank_str = score_rank_text.split("/", 1)
                score_str = score_str.strip()
                rank_str = rank_str.strip()

                # 转成数字用于比较，跳过无效值
                try:
                    score = int(score_str)
                    rank = int(rank_str) if rank_str and rank_str != "-" else None
                except ValueError:
                    continue

                # 提取纯专业名
                major_name = major_full
                if "选科要求：" in major_full:
                    major_name = major_full.split("选科要求：", 1)[0].strip()

                major_scores.append({
                    "score": score,
                    "rank": rank,
                    "major": major_name
                })

            if not major_scores:
                continue

            # 找到分数最低的专业
            min_major = min(major_scores, key=lambda x: x["score"])
            result_list.append({
                "院校名称": school_name,
                "最低分": min_major["score"],
                "最低位次": min_major["rank"] if min_major["rank"] else "无数据",
                "最低分对应专业": min_major["major"]
            })

    # 导出Excel
    if result_list:
        df = pd.DataFrame(result_list)
        # 按最低分从高到低排序，方便查看
        df = df.sort_values("最低分", ascending=False).reset_index(drop=True)
        df.to_excel(output_file, index=False, engine="openpyxl")
        print(f"\n✅ 汇总完成！共统计 {len(result_list)} 所院校")
        print(f"文件已保存至：{os.path.abspath(output_file)}")
    else:
        print("❌ 未提取到有效数据")

if __name__ == "__main__":
    # 配置路径
    FOLDER_PATH = r"D:\NewCode\高考志愿填报系统\data\高考分数线"
    OUTPUT_FILE = "院校最低投档分汇总.xlsx"
    extract_school_min_score(FOLDER_PATH, OUTPUT_FILE)
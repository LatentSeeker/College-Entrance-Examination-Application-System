import os
import pandas as pd
from typing import List

def extract_score_data(folder_path: str, output_file: str = "院校专业分数线汇总.xlsx") -> None:
    """
    批量提取指定文件夹下所有Excel文件中的院校专业分数线，并汇总到新文件
    
    Args:
        folder_path: 存放待提取文件的文件夹路径（绝对路径/相对路径）
        output_file: 汇总结果的输出文件路径（默认生成在当前目录）
    """
    # 存储所有提取的数据
    all_data = []
    # 定义需要提取的核心字段（需根据你的文件实际列名修改！！！）
    # 示例列名：院校名称、专业名称、录取分数线、年份、省份（可增删）
    target_columns = ["院校名称", "专业名称", "录取分数线"]

    # 遍历文件夹下的所有文件
    for file_name in os.listdir(folder_path):
        # 只处理Excel文件（.xlsx/.xls），跳过隐藏文件/非目标文件
        if not (file_name.endswith(".xlsx") or file_name.endswith(".xls")):
            continue
        
        # 拼接完整文件路径
        file_path = os.path.join(folder_path, file_name)
        print(f"正在处理文件：{file_path}")

        try:
            # 读取Excel文件（支持多sheet，自动遍历所有sheet）
            excel_file = pd.ExcelFile(file_path)
            for sheet_name in excel_file.sheet_names:
                # 读取单个sheet，仅保留目标列（不存在的列会显示NaN）
                df = pd.read_excel(file_path, sheet_name=sheet_name, usecols=target_columns)
                # 补充「来源文件」字段，方便溯源
                df["来源文件"] = file_name
                df["来源Sheet"] = sheet_name
                # 过滤空行（分数线为空的行）
                df = df.dropna(subset=["录取分数线"])
                # 添加到总数据列表
                all_data.append(df)

        except Exception as e:
            print(f"处理文件 {file_name} 时出错：{str(e)}，跳过该文件")
            continue

    # 整合所有数据
    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        # 保存汇总结果（Excel格式）
        final_df.to_excel(output_file, index=False, engine="openpyxl")
        print(f"提取完成！汇总文件已保存至：{os.path.abspath(output_file)}")
        print(f"共提取到 {len(final_df)} 条有效数据")
    else:
        print("未提取到任何有效数据，请检查文件路径和列名是否正确")

if __name__ == "__main__":
    # -------------------------- 核心配置（需手动修改！！！） --------------------------
    # 1. 填写存放分数线文件的文件夹路径（示例：Windows路径 "D:/分数线文件"，Mac/Linux "/Users/xxx/分数线文件"）
    FOLDER_PATH = "D:\NewCode\高考志愿填报系统\data\高考分数线"
    # 2. （可选）修改汇总文件的输出路径/名称
    OUTPUT_FILE = "院校专业分数线汇总.xlsx"
    # -------------------------------------------------------------------------------

    # 执行提取
    extract_score_data(folder_path=FOLDER_PATH, output_file=OUTPUT_FILE)
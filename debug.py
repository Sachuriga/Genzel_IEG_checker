import os
import glob
import random
import pandas as pd

# ================= 配置区域 =================
# 请确保路径没有多余的空格，并且不包含中文字符（如果有的话要注意编码）
folder_path = r'/Users/sachuriga/Desktop/for Sachi/' # <--- 请替换为你的真实路径
rat_name = "Rat461707"
# ===========================================

def fix_and_debug():
    print(f"--- 诊断模式启动 ---")
    print(f"目标路径: {folder_path}")
    
    # 1. 检查路径下有没有文件
    search_pattern = os.path.join(folder_path, f"*{rat_name}*.tif")
    all_tif_files = glob.glob(search_pattern)
    
    if not all_tif_files:
        print("\n[错误] 未找到任何文件！")
        print("请检查：")
        print("1. folder_path 是否完全正确？")
        print("2. 文件夹里是否真的包含 .tif 文件？")
        # 尝试列出文件夹里的前5个文件，看看是不是名字不对
        try:
            print("\n文件夹下的前5个文件 (供参考):")
            print(os.listdir(folder_path)[:5])
        except Exception as e:
            print(f"无法读取文件夹: {e}")
        return

    print(f"找到 {len(all_tif_files)} 个文件。正在分析文件名结构...\n")

    # 2. 分析第一个文件，帮你确认 Index
    first_file = os.path.basename(all_tif_files[0])
    # 关键修改：先去掉后缀，再 split
    name_no_ext = os.path.splitext(first_file)[0] 
    parts = name_no_ext.split("_")

    print(f"示例文件名: {first_file}")
    print(f"去除后缀后: {name_no_ext}")
    print("-" * 30)
    for i, p in enumerate(parts):
        print(f"Index [{i}]: {p}")
    print("-" * 30)
    
    # 3. 检查 Index 8 是否正确提取 LH/RH
    print(f"当前逻辑检查 Index [8]: '{parts[8] if len(parts)>8 else 'N/A'}'")
    if len(parts) > 8 and parts[8] in ['LH', 'RH']:
        print(" -> ✅ 成功识别到 LH/RH")
    else:
        print(f" -> ❌ 识别失败，期望是 'LH' 或 'RH'，实际是 '{parts[8] if len(parts)>8 else '越界'}'")

    # 4. 执行筛选测试
    grouped_files = {}
    
    # 用户想要的分组依据 (根据你的描述是 Index 3，但看图可能是 Index 7)
    # 这里我们打印一下 Index 3 和 Index 7 的区别
    unique_ids_idx3 = set()
    unique_ids_idx7 = set()

    for tif_path in all_tif_files:
        fname = os.path.basename(tif_path)
        name_pure = os.path.splitext(fname)[0] # 去掉 .tif
        p = name_pure.split("_")
        
        if len(p) <= 8: continue
        
        # 收集统计信息
        unique_ids_idx3.add(p[3]) # Frontal?
        unique_ids_idx7.add(p[7]) # PrL, vlORB?

        uid = p[3] # 目前代码使用的是 Index 3
        hemi = p[8]

        if uid not in grouped_files: grouped_files[uid] = {'RH': [], 'LH': []}
        if hemi == 'RH': grouped_files[uid]['RH'].append(fname)
        elif hemi == 'LH': grouped_files[uid]['LH'].append(fname)

    print(f"\n[分组统计结果]")
    print(f"如果按 Index 3 ({list(unique_ids_idx3)[0]}) 分组: 共发现 {len(unique_ids_idx3)} 组")
    print(f"如果按 Index 7 ({list(unique_ids_idx7)[0]}...) 分组: 共发现 {len(unique_ids_idx7)} 组")
    
    if len(unique_ids_idx3) == 1:
        print("\n⚠️ 警告: Index 3 似乎对所有文件都一样 (Frontal)。")
        print("这意味着你只会从整个文件夹里一共选出 4 张图。")
        print("如果你想每个脑区 (PrL, vlORB) 各选 4 张，你应该把代码里的 index 改成 7。")

    # 5. 模拟抽样
    total_selected = 0
    print("\n[模拟抽样结果]")
    for uid, data in grouped_files.items():
        n_rh = min(len(data['RH']), 2)
        n_lh = min(len(data['LH']), 2)
        total_selected += (n_rh + n_lh)
        print(f"组 '{uid}': 抽取 RH={n_rh} 张, LH={n_lh} 张")

    print(f"\n总计将选中: {total_selected} 张图片")

if __name__ == "__main__":
    fix_and_debug()
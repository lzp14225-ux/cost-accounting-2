# -*- coding: utf-8 -*-
"""
NXOpen 脚本：提取 .x_t 文件中的红色面数据，结果写入 JSON 文件

只依赖标准库 + NXOpen，不需要 psycopg2 / minio。
由 run_slider_red_face.py 通过 run_journal.exe 调用。

调用方式：
  run_journal.exe run_slider_red_face_in_nx.py -args <input_json> <output_json>

input_json 格式：
  [
    {"subgraph_id": "...", "job_id": "...", "xt_local_path": "C:/tmp/xxx.x_t"},
    ...
  ]

output_json 格式：
  [
    {"subgraph_id": "...", "job_id": "...", "red_face_count": 3, "total_area": 205.5},
    {"subgraph_id": "...", "job_id": "...", "red_face_count": 0, "total_area": 0.0, "error": "no_red_face"},
    ...
  ]
"""

import sys
import os
import json

# NX 红色颜色索引（仅保留 186，确保只统计真正的红色面）
RED_COLORS = {186}


def extract_red_faces(xt_path):
    """
    用 NXOpen 打开 .x_t 文件，提取红色面面积总和和数量。
    返回 (red_face_count, total_area) 或抛出异常。
    """
    import NXOpen

    session = NXOpen.Session.GetSession()
    try:
        opened = session.Parts.Open(xt_path)
        part = opened[0] if isinstance(opened, tuple) else opened
        session.Parts.SetDisplay(part, False, False)
        session.Parts.SetWork(part)
        work_part = session.Parts.Work

        measure_mgr = work_part.MeasureManager
        units = work_part.UnitCollection
        area_unit   = units.FindObject("SquareMilliMeter")
        length_unit = units.FindObject("MilliMeter")

        total_area = 0.0
        red_count  = 0

        for body in work_part.Bodies:
            for face in body.GetFaces():
                try:
                    if face.Color not in RED_COLORS:
                        continue
                    result = measure_mgr.NewFaceProperties(
                        area_unit, length_unit, 0.01, [face]
                    )
                    area = round(result.Area, 3) if hasattr(result, 'Area') else 0.0
                    total_area += area
                    red_count  += 1
                except Exception:
                    pass

        return red_count, round(total_area, 3)

    finally:
        try:
            import NXOpen as _nx
            session.Parts.CloseAll(_nx.BasePart.CloseWholeTree.False_, None)
        except Exception:
            pass


def main():
    # run_journal.exe 传参：脚本名后跟 -args arg1 arg2
    # sys.argv[0] = 脚本路径，-args 之后的才是真正的参数
    raw_args = sys.argv[1:]
    # 去掉 -args 标记（run_journal 会把 -args 后面的内容原样传入）
    if '-args' in raw_args:
        idx = raw_args.index('-args')
        raw_args = raw_args[idx + 1:]

    if len(raw_args) < 2:
        msg = (
            "用法: run_journal.exe run_slider_red_face_in_nx.py "
            "-args <input_json> <output_json>\n"
        )
        sys.stderr.write(msg)
        sys.exit(1)

    input_json_path  = raw_args[0]
    output_json_path = raw_args[1]

    # 读取任务列表
    with open(input_json_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)

    results = []
    for task in tasks:
        subgraph_id = task['subgraph_id']
        job_id      = task['job_id']
        xt_path     = task['xt_local_path']

        sys.stdout.write(f"[NX] 处理: {subgraph_id} -> {xt_path}\n")

        if not os.path.exists(xt_path):
            sys.stderr.write(f"[NX] 文件不存在: {xt_path}\n")
            results.append({
                'subgraph_id': subgraph_id,
                'job_id': job_id,
                'red_face_count': 0,
                'total_area': 0.0,
                'error': 'file_not_found'
            })
            continue

        try:
            red_count, total_area = extract_red_faces(xt_path)
            sys.stdout.write(
                f"[NX] 结果: 红色面={red_count}个, 总面积={total_area}mm2\n"
            )
            entry = {
                'subgraph_id': subgraph_id,
                'job_id': job_id,
                'red_face_count': red_count,
                'total_area': total_area
            }
            if red_count == 0:
                entry['error'] = 'no_red_face'
            results.append(entry)

        except Exception as e:
            sys.stderr.write(f"[NX] 提取失败 {subgraph_id}: {e}\n")
            results.append({
                'subgraph_id': subgraph_id,
                'job_id': job_id,
                'red_face_count': 0,
                'total_area': 0.0,
                'error': str(e)
            })

    # 写出结果 JSON
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    sys.stdout.write(f"[NX] 完成，结果写入: {output_json_path}\n")


if __name__ == '__main__':
    main()

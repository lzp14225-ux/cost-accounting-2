# -*- coding: utf-8 -*-
# NX Journal - 高亮显示识别出的滑块
# 在NX中执行: 菜单 -> 工具 -> Journal -> 执行 -> 选择本文件

import NXOpen

def main():
    session = NXOpen.Session.GetSession()
    slider_names = ['DIE-18']
    prt_file = r"D:\\my_project\\cadagent\\scripts\\slider_recognition\\DIE-21-M250286-P4.prt"

    # 获取当前工作部件，如果没有则打开 PRT
    work_part = session.Parts.Work
    if work_part is None:
        try:
            open_result = session.Parts.Open(prt_file)
            work_part = open_result[0] if isinstance(open_result, tuple) else open_result
            session.Parts.SetWork(work_part)
            work_part = session.Parts.Work
        except Exception as e:
            print(f"打开文件失败: {e}")
            return

    print(f"当前部件: {work_part.Name}")
    print(f"目标滑块: {slider_names}")

    bodies = list(work_part.Bodies)
    shown, hidden = 0, 0

    for body in bodies:
        name = body.Name if body.Name else ""
        is_slider = any(name == s or name.startswith(s + '_') for s in slider_names)
        try:
            if is_slider:
                body.Unblank()
                shown += 1
                print(f"  显示: {name}")
            else:
                body.Blank()
                hidden += 1
        except:
            pass

    try:
        work_part.Views.WorkView.Fit()
    except:
        pass

    print(f"完成: 显示 {shown} 个滑块，隐藏 {hidden} 个实体")

main()

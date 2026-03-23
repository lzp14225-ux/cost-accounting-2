# -*- coding: utf-8 -*-
import NXOpen, os, shutil
LOG = r'C:\Projects\slider_recognition\extract_log.txt'

def log(msg):
    print(msg)
    with open(LOG, 'a', encoding='utf-8') as _f:
        _f.write(msg + '\n')

def main():
    with open(LOG, 'w', encoding='utf-8') as _f:
        _f.write('开始执行\n')
    session = NXOpen.Session.GetSession()
    prt_files = []
    xt_list = [
        (r'C:\Projects\slider_recognition\P3-2026.1.31_split\DIE-03.x_t', r'C:\Projects\slider_recognition\P3-2026.1.31_split\_sliders\DIE-03.prt'),
        (r'C:\Projects\slider_recognition\P3-2026.1.31_split\DIE-06.x_t', r'C:\Projects\slider_recognition\P3-2026.1.31_split\_sliders\DIE-06.prt'),
        (r'C:\Projects\slider_recognition\P3-2026.1.31_split\PH2-03.x_t', r'C:\Projects\slider_recognition\P3-2026.1.31_split\_sliders\PH2-03.prt'),
    ]
    for xt_path, prt_path in xt_list:
        try:
            os.makedirs(os.path.dirname(prt_path), exist_ok=True)
            # 用临时路径绕过 NX session 内部路径缓存导致的 'File already exists'
            tmp_prt = prt_path + '.__tmp__'
            for fp in (tmp_prt, prt_path):
                if os.path.exists(fp):
                    os.remove(fp)
            # 打开 .x_t 文件
            opened = session.Parts.Open(xt_path)
            part = opened[0] if isinstance(opened, tuple) else opened
            session.Parts.SetDisplay(part, False, False)
            session.Parts.SetWork(part)
            work_part = session.Parts.Work
            # Unblank 所有实体（.x_t 导入后实体可能处于 blank 状态）
            for body in work_part.Bodies:
                try:
                    body.Unblank()
                except Exception:
                    pass
            # 另存为临时路径（避免 NX 路径冲突）
            work_part.SaveAs(tmp_prt)
            try:
                work_part.Close(NXOpen.BasePart.CloseWholeTree.TrueValue, None)
            except Exception:
                pass
            # 重命名为最终文件名（先删目标再移动，避免 Windows 覆盖失败）
            if os.path.exists(prt_path): os.remove(prt_path)
            shutil.move(tmp_prt, prt_path)
            log(f'[OK] {os.path.basename(prt_path)}')
            prt_files.append(prt_path)
        except Exception as e:
            log(f'[!] {os.path.basename(xt_path)} 失败: {e}')
    log(f'完成: {len(prt_files)} 个 .prt 文件')

main()
# -*- coding: utf-8 -*-
"""
基于特征面的滑块识别工具 - 增强版
增加了红色面积、周长等基本特征的输出

使用方法:
python recognize_by_features_enhanced.py [拆分文件夹路径]

功能:
1. 读取特征面数据库
2. 分析拆分后的 .x_t 文件
3. 通过特征面匹配识别滑块
4. 输出红色面的面积、周长等基本特征
5. 生成详细的识别报告
"""

import NXOpen
import NXOpen.UF
import json
import os
import sys
import csv
from collections import defaultdict


class FeatureRecognizer:
    """基于特征面的滑块识别器"""
    
    def __init__(self, database_file=None):
        self.session = NXOpen.Session.GetSession()
        self.uf_session = NXOpen.UF.UFSession.GetUFSession()
        # 默认数据库路径：本文件同级目录下的 slider_feature_database.json
        if database_file is None:
            database_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'slider_recognition', 'slider_feature_database.json'
            )
        self.database = self._load_database(database_file)
    
    def _load_database(self, database_file):
        """加载特征面数据库"""
        if not os.path.exists(database_file):
            print(f"错误: 数据库文件不存在: {database_file}")
            return None
        
        with open(database_file, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        print(f"已加载数据库: {database_file}")
        print(f"包含 {len(db['sliders'])} 个滑块模板\n")
        
        return db
    
    def _extract_face_features(self, xt_file):
        """提取 .x_t 文件中所有红色面的特征"""
        try:
            # 打开文件
            part = self.session.Parts.Open(xt_file)
            if isinstance(part, tuple):
                part = part[0]
            
            self.session.Parts.SetDisplay(part, False, False)
            self.session.Parts.SetWork(part)
            work_part = self.session.Parts.Work
            
            # 红色颜色索引（只保留186）
            red_colors = {186}
            
            # 获取所有面
            bodies = list(work_part.Bodies)
            all_faces = []
            for body in bodies:
                faces = list(body.GetFaces())
                all_faces.extend(faces)
            
            # 只提取红色面的特征
            face_features = []
            measure_mgr = work_part.MeasureManager
            units = work_part.UnitCollection
            area_unit = units.FindObject("SquareMilliMeter")
            length_unit = units.FindObject("MilliMeter")
            
            total_area = 0.0
            total_perimeter = 0.0
            total_faces = len(all_faces)
            red_faces = 0
            color_counts = {}
            
            for face in all_faces:
                try:
                    color = face.Color
                    color_counts[color] = color_counts.get(color, 0) + 1
                    
                    # 只处理红色面
                    if color not in red_colors:
                        continue
                    
                    red_faces += 1
                    result = measure_mgr.NewFaceProperties(area_unit, length_unit, 0.01, [face])
                    area = round(result.Area, 3) if hasattr(result, 'Area') else 0.0
                    perimeter = round(result.Perimeter, 3) if hasattr(result, 'Perimeter') else 0.0
                    
                    total_area += area
                    total_perimeter += perimeter
                    
                    face_features.append({
                        'area': area,
                        'perimeter': perimeter,
                        'color': color
                    })
                except Exception as e:
                    print(f"    处理面失败: {e}")
                    pass
            
            print(f"  总面数: {total_faces}, 红色面数: {red_faces}")
            print(f"  颜色分布: {dict(sorted(color_counts.items()))}")
            print(f"  红色面总面积: {total_area:.3f} mm2")
            
            # 关闭文件
            try:
                part_name = work_part.Name
                self.session.Parts.CloseAll(NXOpen.BasePart.CloseWholeTree.False_, None)
            except:
                pass
            
            # 返回特征和统计信息
            return {
                'features': face_features,
                'total_area': round(total_area, 3),
                'total_perimeter': round(total_perimeter, 3),
                'red_face_count': len(face_features)
            }
            
        except Exception as e:
            print(f"  提取失败: {e}")
            return {
                'features': [],
                'total_area': 0.0,
                'total_perimeter': 0.0,
                'red_face_count': 0
            }
    
    def _match_features(self, file_features, template_features):
        """
        匹配红色特征面
        
        逻辑：
        1. 只在红色面中查找匹配
        2. 对于数据库中的每个特征面，在文件的红色面中找最相似的
        3. 计算匹配率
        
        返回匹配得分 (0-100)
        """
        if not file_features or not template_features:
            return 0.0
        
        # 统计模板特征面的面积分布
        template_areas = {}  # area -> count
        for f in template_features:
            area = f['area']
            template_areas[area] = template_areas.get(area, 0) + 1
        
        # 在文件的红色面中查找匹配
        matched_count = 0
        tolerance = 0.05  # 5% 容差
        used_indices = set()  # 记录已匹配的文件面索引，避免重复匹配
        
        for template_face in template_features:
            t_area = template_face['area']
            t_color = template_face['color']
            
            # 在文件的红色面中查找最佳匹配
            best_match_idx = None
            best_diff = float('inf')
            
            for idx, file_face in enumerate(file_features):
                if idx in used_indices:
                    continue
                
                f_area = file_face['area']
                f_color = file_face['color']
                
                # 颜色必须匹配（都是红色）
                if f_color != t_color:
                    continue
                
                # 计算面积差异
                if t_area > 0:
                    diff = abs(f_area - t_area) / t_area
                else:
                    diff = abs(f_area - t_area)
                
                # 在容差范围内，且是最佳匹配
                if diff <= tolerance and diff < best_diff:
                    best_diff = diff
                    best_match_idx = idx
            
            # 如果找到匹配
            if best_match_idx is not None:
                matched_count += 1
                used_indices.add(best_match_idx)
        
        # 计算匹配率
        match_rate = matched_count / len(template_features) * 100
        
        return match_rate
    
    def recognize_file(self, xt_file):
        """
        识别单个 .x_t 文件
        
        返回: (滑块名称, 匹配得分, 详细信息, 特征统计)
        """
        # 提取文件的红色面特征
        extraction_result = self._extract_face_features(xt_file)
        file_features = extraction_result['features']
        
        # 准备统计信息
        stats = {
            'red_face_count': extraction_result['red_face_count'],
            'total_area': extraction_result['total_area'],
            'total_perimeter': extraction_result['total_perimeter']
        }
        
        if not file_features:
            return None, 0.0, "无红色面", stats
        
        # 与数据库中每个滑块模板匹配
        best_match = None
        best_score = 0.0
        best_detail = ""
        
        for slider_name, slider_data in self.database['sliders'].items():
            template_features = slider_data['feature_faces']
            template_count = len(template_features)
            
            score = self._match_features(file_features, template_features)
            
            if score > best_score:
                best_score = score
                best_match = slider_name
                best_detail = f"{len(file_features)}个红色面, 匹配度{score:.1f}%"
        
        # 判断是否识别成功
        if best_score >= 90:
            status = "成功"
        elif best_score >= 70:
            status = "可能"
        else:
            status = "未识别"
            best_match = None
            best_detail = f"{len(file_features)}个红色面, 匹配度{best_score:.1f}%"
        
        return best_match, best_score, best_detail, stats
    
    def _generate_highlight_journal(self, folder_path, slider_names):
        """生成NX Journal文件，用于在NX中高亮显示识别出的滑块"""
        import os
        
        # 找到原始PRT文件（folder_path的上一级同名.prt）
        folder_name = os.path.basename(folder_path.rstrip('/\\'))
        prt_base = folder_name.replace('_split', '')
        prt_path = os.path.join(os.path.dirname(os.path.abspath(folder_path)), prt_base + '.prt')
        prt_path_escaped = prt_path.replace('\\', '\\\\')
        
        slider_list_str = repr(slider_names)
        
        journal_content = f'''# -*- coding: utf-8 -*-
# NX Journal - 高亮显示识别出的滑块
# 在NX中执行: 菜单 -> 工具 -> Journal -> 执行 -> 选择本文件

import NXOpen

def main():
    session = NXOpen.Session.GetSession()
    slider_names = {slider_list_str}
    prt_file = r"{prt_path_escaped}"

    # 获取当前工作部件，如果没有则打开 PRT
    work_part = session.Parts.Work
    if work_part is None:
        try:
            open_result = session.Parts.Open(prt_file)
            work_part = open_result[0] if isinstance(open_result, tuple) else open_result
            session.Parts.SetWork(work_part)
            work_part = session.Parts.Work
        except Exception as e:
            print(f"打开文件失败: {{e}}")
            return

    print(f"当前部件: {{work_part.Name}}")
    print(f"目标滑块: {{slider_names}}")

    bodies = list(work_part.Bodies)
    shown, hidden = 0, 0

    for body in bodies:
        name = body.Name if body.Name else ""
        is_slider = any(name == s or name.startswith(s + \'_\') for s in slider_names)
        try:
            if is_slider:
                body.Unblank()
                shown += 1
                print(f"  显示: {{name}}")
            else:
                body.Blank()
                hidden += 1
        except:
            pass

    try:
        work_part.Views.WorkView.Fit()
    except:
        pass

    print(f"完成: 显示 {{shown}} 个滑块，隐藏 {{hidden}} 个实体")

main()
'''
        
        journal_path = os.path.join(os.path.dirname(folder_path), 'highlight_result.py')
        with open(journal_path, 'w', encoding='utf-8') as f:
            f.write(journal_content)
        
        print(f"\nNX Journal已生成: highlight_result.py")
        print(f"  → 在NX中执行: 菜单 → 工具 → Journal → 执行 → 选择该文件")
        print(f"  → 将显示滑块: {', '.join(slider_names)}")

    def recognize_folder(self, folder_path):
        """识别文件夹中的所有 .x_t 文件"""
        
        print("="*70)
        print("开始识别")
        print("="*70)
        print(f"文件夹: {folder_path}\n")
        
        # 获取所有 .x_t 文件
        xt_files = []
        for file in os.listdir(folder_path):
            if file.endswith('.x_t'):
                xt_files.append(os.path.join(folder_path, file))
        
        print(f"找到 {len(xt_files)} 个 .x_t 文件\n")
        
        # 识别结果
        results = []
        recognized_count = 0
        
        for i, xt_file in enumerate(xt_files, 1):
            file_name = os.path.basename(xt_file)
            print(f"[{i}/{len(xt_files)}] {file_name}", flush=True)
            
            slider_name, score, detail, stats = self.recognize_file(xt_file)
            
            if slider_name:
                print(f"  [OK] 识别为: {slider_name} ({detail})")
                print(f"     红色面: {stats['red_face_count']}个")
                print(f"     总面积: {stats['total_area']} mm2")
                print(f"     总周长: {stats['total_perimeter']} mm")
                recognized_count += 1
            else:
                print(f"  [--] 未识别 ({detail})")
                if stats['red_face_count'] > 0:
                    print(f"     红色面: {stats['red_face_count']}个")
                    print(f"     总面积: {stats['total_area']} mm2")
                    print(f"     总周长: {stats['total_perimeter']} mm")
            
            results.append({
                'file': file_name,
                'slider': slider_name if slider_name else "未识别",
                'score': score,
                'detail': detail,
                'red_face_count': stats['red_face_count'],
                'total_area': stats['total_area'],
                'total_perimeter': stats['total_perimeter']
            })
        
        # 生成报告
        self._generate_report(folder_path, results, recognized_count, len(xt_files))
        
        return results
    
    def _generate_report(self, folder_path, results, recognized_count, total_count):
        """生成识别报告"""
        
        # 过滤掉无红色面的项目
        filtered_results = [r for r in results if r['red_face_count'] > 0]
        no_red_face_count = total_count - len(filtered_results)
        
        # 按匹配得分从高到低排序
        sorted_results = sorted(filtered_results, key=lambda x: x['score'], reverse=True)
        
        # CSV 报告（如果文件被占用则加时间戳）
        from datetime import datetime
        csv_path = os.path.join(folder_path, "特征面识别报告_增强版.csv")
        if os.path.exists(csv_path):
            try:
                open(csv_path, 'a').close()
            except PermissionError:
                ts = datetime.now().strftime("%m%d_%H%M%S")
                csv_path = os.path.join(folder_path, f"特征面识别报告_增强版_{ts}.csv")
        
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['零件名', '识别结果', '匹配得分', '红色面数量', '红色面总面积(mm2)', '红色面总周长(mm)', '详细信息'])
            
            for r in sorted_results:
                # 提取零件名（去掉.x_t后缀）
                part_name = r['file'].replace('.x_t', '').replace('.X_T', '')
                
                writer.writerow([
                    part_name,
                    r['slider'],
                    f"{r['score']:.1f}%",
                    r['red_face_count'],
                    r['total_area'],
                    r['total_perimeter'],
                    r['detail']
                ])
            
            # 添加汇总行
            writer.writerow([])
            writer.writerow(['汇总统计', '', '', '', '', '', ''])
            writer.writerow(['总文件数', total_count, '', '', '', '', ''])
            writer.writerow(['有红色面', len(filtered_results), '', '', '', '', ''])
            writer.writerow(['无红色面(已过滤)', no_red_face_count, '', '', '', '', ''])
            writer.writerow(['识别成功', recognized_count, '', '', '', '', ''])
            writer.writerow(['未识别', len(filtered_results) - recognized_count, '', '', '', '', ''])
        
        # 统计
        slider_counts = defaultdict(int)
        slider_stats = defaultdict(lambda: {'count': 0, 'total_area': 0.0, 'total_perimeter': 0.0})
        
        for r in filtered_results:
            if r['slider'] != "未识别":
                slider_counts[r['slider']] += 1
                slider_stats[r['slider']]['count'] += 1
                slider_stats[r['slider']]['total_area'] += r['total_area']
                slider_stats[r['slider']]['total_perimeter'] += r['total_perimeter']
        
        # 打印总结
        print("\n" + "="*70)
        print("识别完成")
        print("="*70)
        print(f"总文件数: {total_count}")
        print(f"有红色面: {len(filtered_results)}")
        print(f"无红色面(已过滤): {no_red_face_count}")
        print(f"识别成功: {recognized_count}")
        print(f"未识别: {len(filtered_results) - recognized_count}")
        print(f"\n识别统计:")
        for slider in sorted(slider_counts.keys()):
            count = slider_stats[slider]['count']
            avg_area = slider_stats[slider]['total_area'] / count if count > 0 else 0
            avg_perimeter = slider_stats[slider]['total_perimeter'] / count if count > 0 else 0
            print(f"  {slider}: {count} 个")
            print(f"    平均面积: {avg_area:.3f} mm2")
            print(f"    平均周长: {avg_perimeter:.3f} mm")
        print(f"\n报告文件: {csv_path}")
        
        # 生成NX Journal文件，用于在NX中高亮显示识别出的滑块
        recognized_sliders = sorted(set(
            r['slider'] for r in results
            if r['slider'] != "未识别"
        ))
        if recognized_sliders:
            self._generate_highlight_journal(folder_path, recognized_sliders)
        
        print("="*70)


def main():
    """主函数"""
    
    print("="*70)
    print("基于特征面的滑块识别工具 - 增强版")
    print("="*70)
    
    # 检查 NX 环境
    try:
        import NXOpen
        print("检测到 NX 环境\n")
    except ImportError:
        print("错误: 需要在 NX Python 环境中运行")
        return
    
    # 获取文件夹路径（支持相对路径和绝对路径）
    if len(sys.argv) > 1:
        folder_path = os.path.abspath(sys.argv[1])
    else:
        print("使用方法:")
        print("  python recognize_by_features_enhanced.py [拆分文件夹路径]")
        print("\n示例（绝对路径）:")
        print('  python recognize_by_features_enhanced.py "D:\\my_project\\cadagent\\scripts\\slider_recognition\\P3-2026.1.31_split"')
        return
    
    if not os.path.exists(folder_path):
        print(f"错误: 文件夹不存在: {folder_path}")
        return
    
    try:
        # 创建识别器（数据库路径自动定位到 slider_recognition/slider_feature_database.json）
        recognizer = FeatureRecognizer()
        
        if not recognizer.database:
            print("错误: 无法加载数据库")
            return
        
        # 执行识别
        results = recognizer.recognize_folder(folder_path)
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
PRT文件实体分割工具
将包含多个实体的PRT文件分割成多个独立的PRT文件

使用方法:
python prt_split.py [PRT文件路径] [输出文件夹] [--convert] [--extract-features 零件名 面编号1 面编号2 ...]

选项:
--convert  自动将导出的.x_t文件转换为.prt格式
--extract-features  提取指定零件的特征面（在拆分前）

示例:
python prt_split.py "assembly.prt" "split_bodies"
python prt_split.py "assembly.prt" "split_bodies" --extract-features DIE-06 F15226 F15235 F14231
"""

import NXOpen
import NXOpen.UF
import NXOpen.Features
import os
import sys
import glob
import json


class BodySplitter:
    """实体分割器"""
    
    def __init__(self):
        self.session = NXOpen.Session.GetSession()
        self.uf_session = NXOpen.UF.UFSession.GetUFSession()
    
    def extract_feature_faces_before_split(self, prt_file, component_name, face_ids):
        """
        在拆分前提取指定零件的特征面
        
        参数:
            prt_file: PRT文件路径（装配或单个零件）
            component_name: 零件名称（如 "DIE-06"）
            face_ids: 特征面编号列表（如 ["F15226", "F15235", ...]）
        
        返回:
            特征面数据字典
        """
        print("\n" + "="*70)
        print("提取特征面")
        print("="*70)
        print(f"零件: {component_name}")
        print(f"特征面: {', '.join(face_ids)}")
        
        # 打开文件
        try:
            workPart = self.session.Parts.Work
            if not workPart or workPart.FullPath != prt_file:
                res = self.session.Parts.Open(prt_file)
                if isinstance(res, tuple):
                    work_part = res[0]
                else:
                    work_part = res
                self.session.Parts.SetDisplay(work_part, False, False)
                self.session.Parts.SetWork(work_part)
                work_part = self.session.Parts.Work
            else:
                work_part = workPart
        except Exception as e:
            print(f"❌ 无法打开文件: {e}")
            return None
        
        print(f"✓ 文件已打开: {work_part.Name}")
        
        # 尝试作为装配处理
        target_part = None
        is_assembly = False
        
        try:
            root_component = work_part.ComponentAssembly.RootComponent
            if root_component:
                components = root_component.GetChildren()
                if components and len(components) > 0:
                    is_assembly = True
                    # 查找目标零件
                    component = self._find_component(work_part, component_name)
                    if component:
                        target_part = component.Prototype.OwningPart
                        print(f"✓ 在装配中找到零件: {component_name}")
        except:
            pass
        
        # 如果不是装配或未找到组件，直接使用当前零件
        if not is_assembly or not target_part:
            print(f"✓ 作为单个零件处理")
            target_part = work_part
        
        # 获取零件的所有面
        bodies = list(target_part.Bodies)
        print(f"✓ 零件有 {len(bodies)} 个实体")
        
        print(f"✓ 零件有 {len(bodies)} 个实体")
        
        # 收集所有面并建立名称索引
        all_faces = []
        face_by_name = {}
        face_by_uf_name = {}
        
        for body in bodies:
            faces = list(body.GetFaces())
            all_faces.extend(faces)
            
            for face in faces:
                # 通过 face.Name 索引
                try:
                    name = face.Name
                    if name:  # 只有非空名称才索引
                        face_by_name[name] = face
                except:
                    pass
                
                # 通过 UF Name 索引
                try:
                    uf_name = self.uf_session.Obj.AskName(face.Tag)
                    if uf_name:
                        face_by_uf_name[uf_name] = face
                except:
                    pass
        
        print(f"✓ 零件有 {len(all_faces)} 个面")
        print(f"  - 有 Name 属性的面: {len(face_by_name)} 个")
        print(f"  - 有 UF Name 的面: {len(face_by_uf_name)} 个")
        
        # 提取特征面属性
        feature_faces = []
        found_count = 0
        
        print(f"\n查找特征面:")
        for target_id in face_ids:
            face = None
            
            # 方法1: 通过 face.Name 查找
            if target_id in face_by_name:
                face = face_by_name[target_id]
                print(f"  ✓ {target_id} (通过Name属性找到)")
            # 方法2: 通过 UF Name 查找
            elif target_id in face_by_uf_name:
                face = face_by_uf_name[target_id]
                print(f"  ✓ {target_id} (通过UF Name找到)")
            else:
                print(f"  ✗ {target_id}: 未找到")
                continue
            
            # 提取属性
            props = self._extract_face_properties(face, target_part)
            
            if props:
                props['original_face_id'] = target_id
                feature_faces.append(props)
                found_count += 1
                print(f"    面积={props['area']:.3f} mm², 颜色={props['color']}")
            else:
                print(f"    提取失败")
        
        if found_count == 0:
            print("\n❌ 没有提取到任何特征面")
            print("   可能原因:")
            print("   1. 面编号不存在")
            print("   2. 面编号格式不正确")
            print("   3. 面积测量失败")
            print(f"\n💡 提示: 文件中实际有 {len(all_faces)} 个面，其中 {len(face_by_name)} 个有名称")
            print("   可以使用以下命令查看所有面的编号:")
            print(f'   python find_face_by_display_name.py "{prt_file}" {" ".join(face_ids)}')
            return None
        
        # 保存特征面数据
        feature_data = {
            'component_name': component_name,
            'feature_face_count': len(feature_faces),
            'feature_faces': feature_faces,
            'source_file': prt_file
        }
        
        output_file = f"{component_name}_feature_faces.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(feature_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ 特征面数据已保存: {output_file}")
        print(f"  提取成功: {found_count}/{len(face_ids)}")
        print("="*70)
        
        return feature_data
    
    def _find_component(self, work_part, component_name):
        """在装配中查找指定名称的零件"""
        try:
            components = work_part.ComponentAssembly.RootComponent.GetChildren()
            
            for comp in components:
                # 检查零件名称
                if component_name in comp.DisplayName or component_name in comp.Name:
                    return comp
        except:
            pass
        
        return None
    
    def _extract_face_properties(self, face, part):
        """提取面的几何属性"""
        props = {}
        
        # 颜色
        try:
            props['color'] = face.Color
        except:
            props['color'] = -1
        
        # 测量面积和周长（使用与 red_area_autoanylase.py 相同的方法）
        try:
            measure_mgr = part.MeasureManager  # 注意：不带括号
            units = part.UnitCollection
            
            # 获取单位对象
            area_unit = units.FindObject("SquareMilliMeter")
            length_unit = units.FindObject("MilliMeter")
            
            # 设置精度
            accuracy = 0.01
            
            # 调用测量API
            result = measure_mgr.NewFaceProperties(area_unit, length_unit, accuracy, [face])
            
            # 获取结果
            props['area'] = round(result.Area, 3) if hasattr(result, 'Area') else 0.0
            props['perimeter'] = round(result.Perimeter, 3) if hasattr(result, 'Perimeter') else 0.0
            
        except Exception as e:
            print(f"    ⚠️ 测量失败: {e}")
            props['area'] = 0.0
            props['perimeter'] = 0.0
        
        # 面类型和法向量
        try:
            face_tag = face.Tag
            face_type, face_data = self.uf_session.Modl.AskFaceData(face_tag)
            
            type_map = {
                0: "平面",
                1: "圆柱面",
                2: "圆锥面",
                3: "球面",
                4: "圆环面",
                5: "B样条曲面"
            }
            
            props['type'] = face_type
            props['type_name'] = type_map.get(face_type, f"类型{face_type}")
            
            # 如果是平面，记录法向量
            if face_type == 0 and len(face_data) >= 6:
                props['normal'] = [
                    round(face_data[3], 3),
                    round(face_data[4], 3),
                    round(face_data[5], 3)
                ]
            else:
                props['normal'] = None
        except:
            props['type'] = -1
            props['type_name'] = "未知"
            props['normal'] = None
        
        return props
    
    def split_bodies(self, prt_file, output_folder, convert_to_prt=False):
        """分割实体为独立文件"""
        
        print(f"\n正在打开文件: {prt_file}")
        
        # 打开文件
        try:
            workPart = self.session.Parts.Work
            
            if not workPart or workPart.FullPath != prt_file:
                res = self.session.Parts.Open(prt_file)
                if isinstance(res, tuple):
                    work_part = res[0]
                else:
                    work_part = res
                self.session.Parts.SetDisplay(work_part, False, False)
                self.session.Parts.SetWork(work_part)
                work_part = self.session.Parts.Work
            else:
                work_part = workPart
                
        except Exception as e:
            print(f"❌ 无法打开文件: {e}")
            return
        
        print(f"✓ 成功打开: {work_part.Name}")
        
        # 创建输出文件夹
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            print(f"✓ 创建输出文件夹: {output_folder}")
        
        # 获取所有实体
        bodies = list(work_part.Bodies)
        print(f"\n✓ 发现 {len(bodies)} 个实体")
        print("="*60)
        
        # 导出每个实体
        exported_count = 0
        skipped_count = 0
        xt_files = []
        name_counter = {}  # 记录每个名称出现的次数
        
        for i, body in enumerate(bodies, 1):
            try:
                body_name = body.Name if body.Name else f"Body_{i}"
                print(f"\n[{i}/{len(bodies)}] {body_name}")
                
                # 生成输出文件名（处理重复名称）
                safe_name = self._make_safe_filename(body_name)
                
                # 如果名称已存在，添加序号
                if safe_name in name_counter:
                    name_counter[safe_name] += 1
                    unique_name = f"{safe_name}_{name_counter[safe_name]}"
                else:
                    name_counter[safe_name] = 1
                    unique_name = safe_name
                
                output_file = os.path.join(output_folder, f"{unique_name}.x_t")
                
                # 导出为 Parasolid 格式
                success = self._export_body_as_parasolid(work_part, body, output_file)
                
                if success:
                    print(f"  ✓ 已导出: {unique_name}.x_t")
                    exported_count += 1
                    if convert_to_prt:
                        xt_files.append(output_file)
                else:
                    print(f"  ❌ 导出失败")
                    skipped_count += 1
                
            except Exception as e:
                print(f"  ❌ 处理失败: {e}")
                skipped_count += 1
        
        # 总结导出
        print("\n" + "="*60)
        print("分割完成")
        print("="*60)
        print(f"总实体数: {len(bodies)}")
        print(f"成功导出: {exported_count}")
        print(f"跳过/失败: {skipped_count}")
        print(f"输出文件夹: {output_folder}")
        
        # 如果需要转换为PRT
        if convert_to_prt and xt_files:
            print("\n" + "="*60)
            print("开始转换 .x_t 为 .prt")
            print("="*60)
            self._convert_xt_to_prt(xt_files, output_folder)
        else:
            print(f"\n💡 提示: 导出为 Parasolid (.x_t) 格式")
            print(f"   使用 --convert 选项可自动转换为.prt格式")
        
        print("="*60)
    
    def _export_body_as_parasolid(self, work_part, body, output_file):
        """导出实体为Parasolid格式"""
        try:
            # 创建Parasolid导出器
            parasolidCreator = self.session.DexManager.CreateParasolidExporter()
            
            # 设置输出文件
            parasolidCreator.OutputFile = output_file
            
            # 设置导出选项
            parasolidCreator.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
            
            # 选择要导出的实体
            objects = [body]
            added = parasolidCreator.ExportSelectionBlock.SelectionComp.Add(objects)
            
            # 执行导出
            nxObject = parasolidCreator.Commit()
            
            # 清理
            parasolidCreator.Destroy()
            
            return True
            
        except Exception as e:
            print(f"    导出错误: {e}")
            return False
    
    def highlight_sliders_in_prt(self, prt_file, slider_names):
        """
        在NX中打开PRT文件，隐藏所有实体，只显示识别出的滑块实体
        
        参数:
            prt_file: PRT文件路径
            slider_names: 识别出的滑块名称列表，如 ["DIE-06", "DIE-18"]
        """
        print("\n" + "="*70)
        print("在NX中高亮显示滑块")
        print("="*70)
        print(f"文件: {prt_file}")
        print(f"滑块: {', '.join(slider_names)}")

        # 打开文件
        try:
            work_part = self.session.Parts.Work
            if not work_part or work_part.FullPath != prt_file:
                res = self.session.Parts.Open(prt_file)
                if isinstance(res, tuple):
                    work_part = res[0]
                else:
                    work_part = res
                self.session.Parts.SetWork(work_part)
                work_part = self.session.Parts.Work

            # 切换到建模模块并设置为显示部件，让NX界面显示
            self.session.ApplicationSwitchImmediate("UG_APP_MODELING")
            self.session.Parts.SetDisplay(work_part, True, False)
        except Exception as e:
            print(f"❌ 无法打开文件: {e}")
            return False

        print(f"✓ 文件已打开: {work_part.Name}")

        # 获取所有实体
        bodies = list(work_part.Bodies)
        print(f"✓ 共 {len(bodies)} 个实体")

        # 分类：匹配的滑块 vs 其他实体
        matched_bodies = []
        other_bodies = []

        for body in bodies:
            body_name = body.Name if body.Name else ""
            # 精确匹配：零件名完全相同，或以 _数字 结尾的变体（如 DIE-06_2）
            is_slider = any(
                body_name == s or body_name.startswith(s + '_')
                for s in slider_names
            )
            if is_slider:
                matched_bodies.append((body, body_name))
            else:
                other_bodies.append((body, body_name))

        print(f"✓ 匹配滑块: {len(matched_bodies)} 个")
        print(f"✓ 其他实体: {len(other_bodies)} 个（将隐藏）")

        # 隐藏非滑块实体，显示滑块实体
        display_mod = self.session.DisplayManager
        hidden_count = 0
        shown_count = 0

        try:
            for body, name in other_bodies:
                try:
                    body.Blank()
                    hidden_count += 1
                except Exception as e:
                    print(f"  ⚠️ 隐藏失败 {name}: {e}")

            for body, name in matched_bodies:
                try:
                    body.Unblank()
                    shown_count += 1
                    print(f"  ✅ 显示: {name}")
                except Exception as e:
                    print(f"  ⚠️ 显示失败 {name}: {e}")

        except Exception as e:
            print(f"❌ 显示控制失败: {e}")
            return False

        # 刷新视图
        try:
            work_part = self.session.Parts.Work
            work_part.Views.WorkView.Fit()
            self.session.Parts.Work.ModelingViews.WorkView.Regenerate()
        except:
            pass

        print(f"\n✓ 已隐藏: {hidden_count} 个实体")
        print(f"✓ 已显示: {shown_count} 个滑块")
        print("="*70)
        return True

    def restore_all_display(self, prt_file):
        """恢复PRT文件中所有实体的显示"""
        try:
            work_part = self.session.Parts.Work
            if not work_part or work_part.FullPath != prt_file:
                res = self.session.Parts.Open(prt_file)
                if isinstance(res, tuple):
                    work_part = res[0]
                else:
                    work_part = res
                self.session.Parts.SetWork(work_part)
                work_part = self.session.Parts.Work

            self.session.ApplicationSwitchImmediate("UG_APP_MODELING")
            self.session.Parts.SetDisplay(work_part, True, False)

            bodies = list(work_part.Bodies)
            for body in bodies:
                try:
                    body.Unblank()
                except:
                    pass

            try:
                self.session.Parts.Work.Views.WorkView.Fit()
            except:
                pass

            print(f"✓ 已恢复所有 {len(bodies)} 个实体的显示")
            return True
        except Exception as e:
            print(f"❌ 恢复显示失败: {e}")
            return False

    def _make_safe_filename(self, name):
        """生成安全的文件名"""
        # 移除或替换不安全的字符
        unsafe_chars = '<>:"/\\|?*'
        safe_name = name
        for char in unsafe_chars:
            safe_name = safe_name.replace(char, '_')
        return safe_name
    
    def _convert_xt_to_prt(self, xt_files, output_folder):
        """转换.x_t文件为.prt格式"""
        
        success_count = 0
        fail_count = 0
        
        for i, xt_file in enumerate(xt_files, 1):
            file_name = os.path.basename(xt_file)
            base_name = os.path.splitext(file_name)[0]
            
            print(f"\n[{i}/{len(xt_files)}] {file_name}")
            
            # 生成输出文件名
            output_prt = os.path.join(output_folder, f"{base_name}.prt")
            
            # 检查是否已存在
            if os.path.exists(output_prt):
                print(f"  ⚠️ PRT已存在，跳过")
                success_count += 1
                continue
            
            # 转换
            try:
                # 打开.x_t文件
                opened_part = self.session.Parts.Open(xt_file)
                
                if isinstance(opened_part, tuple):
                    opened_part = opened_part[0]
                
                # 设置为显示部件
                self.session.Parts.SetDisplay(opened_part, False, False)
                self.session.Parts.SetWork(opened_part)
                
                # 另存为.prt格式
                part_save_status = opened_part.SaveAs(output_prt)
                
                print(f"  ✓ 转换成功: {base_name}.prt")
                success_count += 1
                
            except Exception as e:
                print(f"  ❌ 转换失败: {e}")
                fail_count += 1
        
        # 转换总结
        print("\n" + "="*60)
        print("转换完成")
        print("="*60)
        print(f"总文件数: {len(xt_files)}")
        print(f"转换成功: {success_count}")
        print(f"失败: {fail_count}")


def main():
    """主函数"""
    print("="*60)
    print("PRT文件实体分割工具")
    print("="*60)

    if len(sys.argv) < 2:
        print("\n使用方法:")
        print("  python prt_split.py [PRT文件] [输出文件夹] [选项]")
        print("\n示例:")
        print('  python prt_split.py "assembly.prt" "split_bodies"')
        print('  python prt_split.py "assembly.prt" "split_bodies" --convert')
        print('  python prt_split.py "assembly.prt" --extract-features DIE-06 F15226 F15235 F14231')
        print('  python prt_split.py "assembly.prt" --highlight DIE-06 DIE-18 DIE-21')
        print('  python prt_split.py "assembly.prt" --restore')
        print("\n选项:")
        print("  --convert              自动将导出的.x_t文件转换为.prt格式")
        print("  --extract-features     提取指定零件的特征面（在拆分前）")
        print("                         格式: --extract-features 零件名 面编号1 面编号2 ...")
        print("  --highlight            在NX中只显示指定的滑块，隐藏其他实体")
        print("                         格式: --highlight DIE-06 DIE-18 ...")
        print("  --restore              恢复PRT文件中所有实体的显示")
        print("\n说明:")
        print("  - 将PRT文件中的每个实体导出为独立的Parasolid文件(.x_t)")
        print("  - 使用 --convert 选项可自动转换为.prt格式")
        print("  - 使用 --extract-features 可在拆分前提取特征面")
        return
    
    prt_file = sys.argv[1]
    
    if not os.path.exists(prt_file):
        print(f"❌ 文件不存在: {prt_file}")
        return
    
    splitter = BodySplitter()
    
    # 检查是否有 --highlight 选项
    if '--highlight' in sys.argv:
        highlight_idx = sys.argv.index('--highlight')
        slider_names = []
        idx = highlight_idx + 1
        while idx < len(sys.argv) and not sys.argv[idx].startswith('--'):
            slider_names.append(sys.argv[idx])
            idx += 1
        if not slider_names:
            print("❌ --highlight 需要至少一个滑块名称")
            return
        splitter.highlight_sliders_in_prt(prt_file, slider_names)
        return

    # 检查是否有 --restore 选项
    if '--restore' in sys.argv:
        splitter.restore_all_display(prt_file)
        return

    # 检查是否有 --extract-features 选项
    if '--extract-features' in sys.argv:
        extract_idx = sys.argv.index('--extract-features')
        
        if extract_idx + 1 >= len(sys.argv):
            print("❌ --extract-features 需要指定零件名和面编号")
            return
        
        component_name = sys.argv[extract_idx + 1]
        
        # 收集面编号（直到遇到下一个选项或参数结束）
        face_ids = []
        idx = extract_idx + 2
        while idx < len(sys.argv) and not sys.argv[idx].startswith('--'):
            face_ids.append(sys.argv[idx])
            idx += 1
        
        if not face_ids:
            print("❌ --extract-features 需要至少一个面编号")
            return
        
        # 提取特征面
        splitter.extract_feature_faces_before_split(prt_file, component_name, face_ids)
        
        # 如果只是提取特征面，不进行拆分，则返回
        if len(sys.argv) == idx:
            return
    
    # 检查是否有 --convert 选项
    convert_to_prt = '--convert' in sys.argv
    
    # 确定输出文件夹
    output_folder = None
    for i, arg in enumerate(sys.argv[2:], 2):
        if not arg.startswith('--') and arg not in ['--convert', '--extract-features']:
            # 检查这个参数不是 --extract-features 后面的参数
            if i > 2 and sys.argv[i-1] != '--extract-features':
                output_folder = arg
                break
    
    if not output_folder:
        # 使用文件名作为输出文件夹
        base_name = os.path.splitext(os.path.basename(prt_file))[0]
        output_folder = os.path.join(os.path.dirname(prt_file), f"{base_name}_split")
    
    # 执行拆分
    splitter.split_bodies(prt_file, output_folder, convert_to_prt)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()

# -*- coding: utf-8 -*-
"""
在 MinIO 中查找文件的工具脚本
"""

import sys
from minio_client import minio_client

def find_file_by_uuid(uuid: str):
    """根据 UUID 在 MinIO 中查找文件"""
    
    print("=" * 80)
    print(f"在 MinIO 中查找文件: {uuid}")
    print("=" * 80)
    
    # 可能的路径模式
    patterns = [
        f"dwg/2026/03/{uuid}.dwg",
        f"dwg/2026/02/{uuid}.dwg",
        f"dwg/2026/01/{uuid}.dwg",
        f"dwg/2025/**/{uuid}.dwg",
    ]
    
    print("\n检查常见路径...")
    found = False
    
    for pattern in patterns:
        if '**' in pattern:
            # 需要递归搜索
            prefix = pattern.split('**')[0]
            print(f"\n搜索: {prefix}...")
            try:
                objects = minio_client.client.list_objects(
                    minio_client.bucket_files,
                    prefix=prefix,
                    recursive=True
                )
                
                for obj in objects:
                    if uuid in obj.object_name and obj.object_name.endswith('.dwg'):
                        print(f"✅ 找到文件: {obj.object_name}")
                        print(f"   大小: {obj.size / 1024:.2f} KB")
                        print(f"   修改时间: {obj.last_modified}")
                        found = True
            except Exception as e:
                print(f"   搜索失败: {e}")
        else:
            # 直接检查
            exists = minio_client.file_exists(pattern)
            if exists:
                print(f"✅ 找到文件: {pattern}")
                try:
                    stat = minio_client.client.stat_object(
                        minio_client.bucket_files,
                        pattern
                    )
                    print(f"   大小: {stat.size / 1024:.2f} KB")
                    print(f"   修改时间: {stat.last_modified}")
                    found = True
                except:
                    pass
            else:
                print(f"❌ 不存在: {pattern}")
    
    if not found:
        print("\n" + "=" * 80)
        print("未找到文件，可能的原因：")
        print("=" * 80)
        print("1. 文件从未上传到 MinIO")
        print("2. 文件已被删除")
        print("3. 文件在其他存储桶中")
        print("4. UUID 记录错误")
        print("\n建议：")
        print("- 检查数据库中的 job 记录是否正确")
        print("- 查看文件上传日志")
        print("- 联系管理员确认文件状态")
    
    return found


def list_recent_files(limit=20):
    """列出最近上传的文件"""
    
    print("\n" + "=" * 80)
    print(f"MinIO 中最近的 {limit} 个 DWG 文件")
    print("=" * 80)
    
    try:
        objects = minio_client.client.list_objects(
            minio_client.bucket_files,
            prefix='dwg/',
            recursive=True
        )
        
        # 按修改时间排序
        dwg_files = [obj for obj in objects if obj.object_name.endswith('.dwg')]
        dwg_files.sort(key=lambda x: x.last_modified, reverse=True)
        
        if dwg_files:
            print(f"\n找到 {len(dwg_files)} 个 DWG 文件，显示最近 {limit} 个:\n")
            for i, obj in enumerate(dwg_files[:limit], 1):
                size_mb = obj.size / 1024 / 1024
                print(f"{i:3d}. {obj.object_name}")
                print(f"     大小: {size_mb:.2f} MB, 修改时间: {obj.last_modified}")
        else:
            print("⚠️ 没有找到 DWG 文件")
    
    except Exception as e:
        print(f"❌ 列出文件失败: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 从命令行参数获取 UUID
        uuid = sys.argv[1]
        # 移除可能的 .dwg 后缀
        if uuid.endswith('.dwg'):
            uuid = uuid[:-4]
        find_file_by_uuid(uuid)
    else:
        print("用法: python find_file_in_minio.py <UUID>")
        print("示例: python find_file_in_minio.py 7d5b0ad0-b423-4d64-a82b-c3ca536ee49c")
        print("\n或者查看最近的文件:")
        list_recent_files(20)

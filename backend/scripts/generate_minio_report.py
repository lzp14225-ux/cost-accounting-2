# -*- coding: utf-8 -*-
"""
生成 MinIO 文件报告
无需数据库连接，可以发送给数据库管理员
"""

from minio_client import minio_client
from datetime import datetime
import json

def generate_report():
    """生成 MinIO 文件报告"""
    
    print("=" * 80)
    print("生成 MinIO 文件报告")
    print("=" * 80)
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'total_files': 0,
        'total_size_bytes': 0,
        'files_by_month': {},
        'files': []
    }
    
    print("\n正在扫描 MinIO...")
    
    try:
        objects = minio_client.client.list_objects(
            minio_client.bucket_files,
            prefix='dwg/',
            recursive=True
        )
        
        for obj in objects:
            if obj.object_name.endswith('.dwg'):
                report['total_files'] += 1
                report['total_size_bytes'] += obj.size
                
                # 提取年月
                parts = obj.object_name.split('/')
                if len(parts) >= 3:
                    year_month = f"{parts[1]}/{parts[2]}"
                    report['files_by_month'][year_month] = report['files_by_month'].get(year_month, 0) + 1
                
                # 提取 UUID
                uuid = obj.object_name.split('/')[-1].replace('.dwg', '')
                
                report['files'].append({
                    'uuid': uuid,
                    'path': obj.object_name,
                    'size': obj.size,
                    'modified': obj.last_modified.isoformat()
                })
        
        # 按修改时间排序
        report['files'].sort(key=lambda x: x['modified'], reverse=True)
        
        # 生成文本报告
        txt_file = 'minio_report.txt'
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write("MinIO DWG 文件报告\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成时间: {report['generated_at']}\n")
            f.write(f"总文件数: {report['total_files']}\n")
            f.write(f"总大小: {report['total_size_bytes'] / 1024 / 1024 / 1024:.2f} GB\n")
            f.write(f"平均大小: {report['total_size_bytes'] / report['total_files'] / 1024 / 1024:.2f} MB\n" if report['total_files'] > 0 else "")
            f.write("\n按月份统计:\n")
            for year_month in sorted(report['files_by_month'].keys(), reverse=True):
                f.write(f"  {year_month}: {report['files_by_month'][year_month]} 个文件\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("所有文件列表（按上传时间倒序）\n")
            f.write("=" * 80 + "\n\n")
            
            for i, file_info in enumerate(report['files'], 1):
                f.write(f"{i:4d}. UUID: {file_info['uuid']}\n")
                f.write(f"      路径: {file_info['path']}\n")
                f.write(f"      大小: {file_info['size'] / 1024 / 1024:.2f} MB\n")
                f.write(f"      时间: {file_info['modified']}\n\n")
        
        # 生成 JSON 报告
        json_file = 'minio_report.json'
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 生成 UUID 列表（便于数据库管理员查询）
        uuid_file = 'minio_uuids.txt'
        with open(uuid_file, 'w', encoding='utf-8') as f:
            f.write("MinIO 中存在的所有 DWG 文件 UUID\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成时间: {report['generated_at']}\n")
            f.write(f"总数: {report['total_files']}\n\n")
            
            for file_info in report['files']:
                f.write(f"{file_info['uuid']}\n")
        
        print(f"\n✅ 报告生成完成:")
        print(f"  - 文本报告: {txt_file}")
        print(f"  - JSON 报告: {json_file}")
        print(f"  - UUID 列表: {uuid_file}")
        
        print(f"\n📊 统计信息:")
        print(f"  总文件数: {report['total_files']}")
        print(f"  总大小: {report['total_size_bytes'] / 1024 / 1024 / 1024:.2f} GB")
        
        print(f"\n💡 使用建议:")
        print(f"  1. 将 {uuid_file} 发送给数据库管理员")
        print(f"  2. 数据库管理员可以查询哪些 job 的文件不在这个列表中")
        print(f"  3. SQL 示例:")
        print(f"     SELECT job_id, dwg_file_path")
        print(f"     FROM jobs")
        print(f"     WHERE dwg_file_path NOT LIKE ANY(SELECT '%' || uuid || '%' FROM minio_uuids)")
        
    except Exception as e:
        print(f"❌ 生成报告失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    generate_report()

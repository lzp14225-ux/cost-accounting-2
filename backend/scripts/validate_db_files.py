# -*- coding: utf-8 -*-
"""
验证数据库中的文件记录是否在 MinIO 中存在
需要安装: pip install psycopg2-binary
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from minio_client import minio_client

# 加载环境变量
load_dotenv()

# 尝试导入数据库模块
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from cad_chaitu.database import DatabaseManager
    
    db_manager = DatabaseManager(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    DB_AVAILABLE = True
except Exception as e:
    print(f"⚠️ 数据库模块不可用: {e}")
    print("请安装: pip install psycopg2-binary")
    DB_AVAILABLE = False


def validate_recent_jobs(limit=20):
    """验证最近的 jobs 记录"""
    
    if not DB_AVAILABLE:
        print("❌ 数据库不可用，无法执行验证")
        return
    
    print("=" * 80)
    print(f"验证最近 {limit} 条 jobs 记录")
    print("=" * 80)
    
    import psycopg2
    
    conn = None
    try:
        conn = db_manager.db_pool.getconn()
        cursor = conn.cursor()
        
        # 查询最近的 jobs
        cursor.execute("""
            SELECT job_id, dwg_file_path, prt_file_path, created_at
            FROM jobs
            WHERE dwg_file_path IS NOT NULL
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        
        jobs = cursor.fetchall()
        
        if not jobs:
            print("⚠️ 没有找到 jobs 记录")
            return
        
        print(f"\n找到 {len(jobs)} 条记录\n")
        
        valid_count = 0
        invalid_count = 0
        invalid_jobs = []
        
        for job_id, dwg_path, prt_path, created_at in jobs:
            print(f"Job ID: {job_id}")
            print(f"  创建时间: {created_at}")
            print(f"  DWG 路径: {dwg_path}")
            
            # 检查 DWG 文件
            if dwg_path:
                exists = minio_client.file_exists(dwg_path)
                if exists:
                    print(f"  DWG 状态: ✅ 存在")
                    valid_count += 1
                else:
                    print(f"  DWG 状态: ❌ 不存在")
                    invalid_count += 1
                    invalid_jobs.append({
                        'job_id': job_id,
                        'file_path': dwg_path,
                        'file_type': 'DWG',
                        'created_at': created_at
                    })
            
            # 检查 PRT 文件
            if prt_path:
                print(f"  PRT 路径: {prt_path}")
                exists = minio_client.file_exists(prt_path)
                if exists:
                    print(f"  PRT 状态: ✅ 存在")
                else:
                    print(f"  PRT 状态: ❌ 不存在")
                    invalid_jobs.append({
                        'job_id': job_id,
                        'file_path': prt_path,
                        'file_type': 'PRT',
                        'created_at': created_at
                    })
            
            print()
        
        # 统计结果
        print("=" * 80)
        print("验证结果")
        print("=" * 80)
        print(f"总记录数: {len(jobs)}")
        print(f"有效文件: {valid_count}")
        print(f"无效文件: {invalid_count}")
        print(f"有效率: {valid_count / (valid_count + invalid_count) * 100:.1f}%" if (valid_count + invalid_count) > 0 else "N/A")
        
        if invalid_jobs:
            print("\n" + "=" * 80)
            print("无效记录详情")
            print("=" * 80)
            
            # 导出到文件
            output_file = "invalid_jobs.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write("无效的 Job 记录\n")
                f.write("=" * 80 + "\n")
                f.write(f"生成时间: {created_at}\n\n")
                
                for i, job in enumerate(invalid_jobs, 1):
                    print(f"\n{i}. Job ID: {job['job_id']}")
                    print(f"   类型: {job['file_type']}")
                    print(f"   路径: {job['file_path']}")
                    print(f"   创建时间: {job['created_at']}")
                    
                    f.write(f"\n{i}. Job ID: {job['job_id']}\n")
                    f.write(f"   类型: {job['file_type']}\n")
                    f.write(f"   路径: {job['file_path']}\n")
                    f.write(f"   创建时间: {job['created_at']}\n")
                    
                    # 提取 UUID
                    uuid = Path(job['file_path']).stem
                    f.write(f"   UUID: {uuid}\n")
            
            print(f"\n✅ 无效记录已导出到: {output_file}")
            
            # 提供修复建议
            print("\n" + "=" * 80)
            print("修复建议")
            print("=" * 80)
            print("""
方案1: 重新上传文件
  - 找到原始文件并重新上传到 MinIO
  - 确保路径与数据库记录一致

方案2: 更新数据库记录
  - 如果文件在其他位置，更新数据库路径
  - SQL: UPDATE jobs SET dwg_file_path = '正确路径' WHERE job_id = 'xxx'

方案3: 删除无效记录
  - 如果文件确实丢失且无法恢复
  - SQL: DELETE FROM jobs WHERE job_id = 'xxx'

方案4: 联系上游系统
  - 检查文件上传流程
  - 确认为什么文件没有上传成功
            """)
        else:
            print("\n✅ 所有记录都有效！")
        
        cursor.close()
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if conn:
            db_manager.db_pool.putconn(conn)


def check_specific_job(job_id):
    """检查特定的 job"""
    
    if not DB_AVAILABLE:
        print("❌ 数据库不可用")
        return
    
    print("=" * 80)
    print(f"检查 Job: {job_id}")
    print("=" * 80)
    
    dwg_path = db_manager.get_dwg_file_path(job_id)
    prt_path = db_manager.get_prt_file_path(job_id)
    
    if not dwg_path:
        print(f"⚠️ 数据库中没有找到该 job_id")
        return
    
    print(f"\n数据库记录:")
    print(f"  DWG: {dwg_path}")
    if prt_path:
        print(f"  PRT: {prt_path}")
    
    print(f"\nMinIO 验证:")
    
    # 检查 DWG
    dwg_exists = minio_client.file_exists(dwg_path)
    print(f"  DWG: {'✅ 存在' if dwg_exists else '❌ 不存在'}")
    
    if not dwg_exists:
        uuid = Path(dwg_path).stem
        print(f"\n  尝试查找文件...")
        os.system(f'python find_file_in_minio.py {uuid}')
    
    # 检查 PRT
    if prt_path:
        prt_exists = minio_client.file_exists(prt_path)
        print(f"  PRT: {'✅ 存在' if prt_exists else '❌ 不存在'}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 检查特定 job
        job_id = sys.argv[1]
        check_specific_job(job_id)
    else:
        # 验证最近的记录
        validate_recent_jobs(20)

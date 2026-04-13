from minio import Minio
import os

# MinIO 配置
client = Minio(
    "192.168.3.61:9000",
    access_key="你的AccessKey",  # 替换成你的 AccessKey
    secret_key="你的SecretKey",  # 替换成你的 SecretKey
    secure=False
)

# 本地文件路径（你提供的）
local_file = r"D:\my_project\cadagent\scripts\P3-2026.1.31.dwg"

# MinIO 中的目标路径
minio_path = "dwg/2026/03/4730890d-cfd7-4b32-9846-f25328831f63.dwg"

try:
    # 检查本地文件是否存在
    if not os.path.exists(local_file):
        print(f"❌ 本地文件不存在: {local_file}")
        exit(1)
    
    print(f"📁 本地文件大小: {os.path.getsize(local_file)} 字节")
    
    # 方案1：用二进制方式打开文件并上传
    print("🔄 尝试用二进制方式上传...")
    
    # 使用 put_object 而不是 fput_object
    with open(local_file, 'rb') as file_data:
        file_stat = os.stat(local_file)
        
        result = client.put_object(
            "files",
            minio_path,
            file_data,
            file_stat.st_size,
            content_type="application/octet-stream"
        )
    
    print(f"✅ 上传成功!")
    print(f"   Bucket: files")
    print(f"   Object: {minio_path}")
    
    # 验证文件是否上传成功
    print("\n🔍 验证文件是否存在...")
    obj_info = client.stat_object("files", minio_path)
    print(f"✅ 验证成功，文件大小: {obj_info.size} 字节")
    
except Exception as e:
    print(f"❌ 上传失败: {e}")
    import traceback
    traceback.print_exc()
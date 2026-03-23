import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def export_features_to_json(job_id, output_file='features_export.json'):
    """
    从数据库查询特征数据并导出为JSON文件
    
    Args:
        job_id: 任务ID
        output_file: 输出JSON文件路径
    """
    
    # 数据库连接配置（从环境变量读取）
    conn_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    query = """
        SELECT 
            s.part_name,          -- 零件名称
            s.part_code,          -- 零件编号
            f.length_mm,
            f.width_mm,
            f.thickness_mm,
            f.material,
            f.heat_treatment,
            f.calculated_weight_kg,
            f.top_view_wire_length,
            f.front_view_wire_length,
            f.side_view_wire_length,
            f.processing_instructions,
            f.abnormal_situation,
            f.metadata,
            f.water_mill,
            f.tooth_hole,
            F.boring_num
        FROM public.features f
        JOIN public.subgraphs s
        ON s.subgraph_id = f.subgraph_id
        AND s.job_id = f.job_id
        WHERE f.job_id = %s
        ORDER BY s.subgraph_id, f.feature_id;
    """
    
    try:
        # 连接数据库
        print(f"正在连接数据库...")
        conn = psycopg2.connect(**conn_params)
        
        # 使用RealDictCursor以字典形式返回结果
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # 执行查询
        print(f"正在查询 job_id: {job_id} 的数据...")
        cursor.execute(query, (job_id,))
        
        # 获取所有结果
        results = cursor.fetchall()
        
        # 转换为普通字典列表（处理特殊类型）
        data = []
        for row in results:
            row_dict = dict(row)
            # 处理可能的特殊类型（如Decimal、datetime等）
            for key, value in row_dict.items():
                if isinstance(value, datetime):
                    row_dict[key] = value.isoformat()
                elif hasattr(value, '__float__'):
                    row_dict[key] = float(value)
            data.append(row_dict)
        
        # 保存为JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 成功导出 {len(data)} 条记录到 {output_file}")
        
        # 关闭连接
        cursor.close()
        conn.close()
        
        return data
        
    except psycopg2.Error as e:
        print(f"✗ 数据库错误: {e}")
        raise
    except Exception as e:
        print(f"✗ 错误: {e}") 
        raise


if __name__ == "__main__":
    # 使用示例
    # 760f6b64-349a-48ff-80cf-10ec0c63e28a    34
    job_id = "1a0afea4-1ce8-4f4d-aea9-6eb4118cb39c"
    output_file = 'features_export.json'
    export_features_to_json(job_id, output_file)
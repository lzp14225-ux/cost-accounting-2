"""
并发监控脚本
用于观察队列消费的并发情况和资源使用

运行方式：
    python scripts/monitor_concurrency.py
"""
import asyncio
import psutil
import time
from datetime import datetime
from shared.message_queue import MessageQueue, QUEUE_JOB_PROCESSING, QUEUE_PRICING_RECALCULATE
from shared.database import get_db
from sqlalchemy import text

async def get_queue_stats(mq: MessageQueue, queue_name: str):
    """获取队列统计信息"""
    try:
        # 声明队列
        queue = await mq.channel.declare_queue(queue_name, passive=True)
        return {
            "name": queue_name,
            "messages": queue.declaration_result.message_count,
            "consumers": queue.declaration_result.consumer_count
        }
    except Exception as e:
        return {
            "name": queue_name,
            "messages": "N/A",
            "consumers": "N/A",
            "error": str(e)
        }

async def get_db_connections():
    """获取数据库连接数"""
    try:
        async for db in get_db():
            result = await db.execute(text("""
                SELECT count(*) as total,
                       count(*) FILTER (WHERE state = 'active') as active,
                       count(*) FILTER (WHERE state = 'idle') as idle
                FROM pg_stat_activity
                WHERE datname = current_database()
            """))
            row = result.fetchone()
            return {
                "total": row[0],
                "active": row[1],
                "idle": row[2]
            }
    except Exception as e:
        return {"error": str(e)}

async def monitor():
    """监控主函数"""
    print("=" * 80)
    print("队列并发监控")
    print("=" * 80)
    print("按 Ctrl+C 停止监控\n")
    
    mq = MessageQueue()
    await mq.connect()
    
    try:
        while True:
            # 获取系统资源
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # 获取队列统计
            job_queue = await get_queue_stats(mq, QUEUE_JOB_PROCESSING)
            pricing_queue = await get_queue_stats(mq, QUEUE_PRICING_RECALCULATE)
            
            # 获取数据库连接
            db_conn = await get_db_connections()
            
            # 清屏（可选）
            # print("\033[2J\033[H")
            
            # 打印监控信息
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now}]")
            print("-" * 80)
            
            # 系统资源
            print(f"📊 系统资源:")
            print(f"  CPU使用率: {cpu_percent:.1f}%")
            print(f"  内存使用率: {memory.percent:.1f}% ({memory.used / 1024**3:.1f}GB / {memory.total / 1024**3:.1f}GB)")
            
            # 队列状态
            print(f"\n📬 队列状态:")
            print(f"  任务编排队列 ({QUEUE_JOB_PROCESSING}):")
            print(f"    - 待处理消息: {job_queue['messages']}")
            print(f"    - 消费者数量: {job_queue['consumers']}")
            
            print(f"  价格重算队列 ({QUEUE_PRICING_RECALCULATE}):")
            print(f"    - 待处理消息: {pricing_queue['messages']}")
            print(f"    - 消费者数量: {pricing_queue['consumers']}")
            
            # 数据库连接
            if "error" not in db_conn:
                print(f"\n🗄️  数据库连接:")
                print(f"  总连接数: {db_conn['total']}")
                print(f"  活跃连接: {db_conn['active']}")
                print(f"  空闲连接: {db_conn['idle']}")
                
                # 连接池使用率警告
                if db_conn['total'] > 15:
                    print(f"  ⚠️  警告: 连接数较高，建议降低并发数")
            
            # 建议
            print(f"\n💡 建议:")
            if cpu_percent > 80:
                print(f"  ⚠️  CPU使用率过高，考虑降低并发数")
            if memory.percent > 80:
                print(f"  ⚠️  内存使用率过高，考虑降低并发数")
            if job_queue['messages'] > 10:
                print(f"  📈 任务编排队列积压，考虑增加并发数")
            if pricing_queue['messages'] > 20:
                print(f"  📈 价格重算队列积压，考虑增加并发数")
            
            print("-" * 80)
            
            # 等待5秒
            await asyncio.sleep(5)
            
    except KeyboardInterrupt:
        print("\n\n监控已停止")
    finally:
        await mq.close()

if __name__ == "__main__":
    asyncio.run(monitor())

"""
数据库锁监控脚本
实时监控数据库锁情况，帮助诊断并发问题

运行方式：
    python scripts/monitor_locks.py
"""
import asyncio
from datetime import datetime
from shared.database import get_db
from sqlalchemy import text

async def check_locks():
    """检查数据库锁情况"""
    async for db in get_db():
        # 1. 查看活跃的锁
        result = await db.execute(text("""
            SELECT 
                l.locktype,
                CASE 
                    WHEN l.relation IS NOT NULL THEN l.relation::regclass::text
                    ELSE 'N/A'
                END AS table_name,
                l.mode,
                l.granted,
                a.pid,
                a.usename,
                a.application_name,
                a.state,
                LEFT(a.query, 100) AS query,
                EXTRACT(EPOCH FROM (now() - a.query_start)) AS duration_seconds
            FROM pg_locks l
            JOIN pg_stat_activity a ON l.pid = a.pid
            WHERE a.datname = current_database()
              AND a.pid != pg_backend_pid()
            ORDER BY a.query_start
        """))
        
        locks = result.fetchall()
        
        # 2. 查看正在等待的锁
        result = await db.execute(text("""
            SELECT 
                blocked_locks.pid AS blocked_pid,
                blocked_activity.usename AS blocked_user,
                blocking_locks.pid AS blocking_pid,
                blocking_activity.usename AS blocking_user,
                LEFT(blocked_activity.query, 100) AS blocked_statement,
                LEFT(blocking_activity.query, 100) AS blocking_statement
            FROM pg_catalog.pg_locks blocked_locks
            JOIN pg_catalog.pg_stat_activity blocked_activity 
                ON blocked_activity.pid = blocked_locks.pid
            JOIN pg_catalog.pg_locks blocking_locks 
                ON blocking_locks.locktype = blocked_locks.locktype
                AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
                AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
                AND blocking_locks.pid != blocked_locks.pid
            JOIN pg_catalog.pg_stat_activity blocking_activity 
                ON blocking_activity.pid = blocking_locks.pid
            WHERE NOT blocked_locks.granted
        """))
        
        waiting_locks = result.fetchall()
        
        # 3. 查看长时间运行的事务
        result = await db.execute(text("""
            SELECT 
                pid,
                usename,
                application_name,
                state,
                EXTRACT(EPOCH FROM (now() - xact_start)) AS transaction_duration,
                EXTRACT(EPOCH FROM (now() - query_start)) AS query_duration,
                LEFT(query, 100) AS query
            FROM pg_stat_activity
            WHERE state != 'idle'
              AND xact_start IS NOT NULL
              AND now() - xact_start > interval '10 seconds'
            ORDER BY xact_start
        """))
        
        long_transactions = result.fetchall()
        
        return {
            "locks": locks,
            "waiting_locks": waiting_locks,
            "long_transactions": long_transactions
        }

async def monitor():
    """监控主函数"""
    print("=" * 80)
    print("数据库锁监控")
    print("=" * 80)
    print("按 Ctrl+C 停止监控\n")
    
    try:
        while True:
            data = await check_locks()
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now}]")
            print("-" * 80)
            
            # 显示活跃的锁
            locks = data["locks"]
            if locks:
                print(f"🔒 活跃的锁 ({len(locks)} 个):")
                for lock in locks[:10]:  # 只显示前10个
                    granted = "✅" if lock[3] else "⏳"
                    print(f"  {granted} {lock[1]} | {lock[2]} | PID:{lock[4]} | {lock[6]} | {lock[7]}")
                    if lock[9] > 5:  # 超过5秒
                        print(f"     ⚠️  持续时间: {lock[9]:.1f}秒")
                if len(locks) > 10:
                    print(f"  ... 还有 {len(locks) - 10} 个锁")
            else:
                print("🔒 活跃的锁: 无")
            
            # 显示等待的锁（重点关注）
            waiting_locks = data["waiting_locks"]
            if waiting_locks:
                print(f"\n⚠️  正在等待的锁 ({len(waiting_locks)} 个):")
                for wlock in waiting_locks:
                    print(f"  被阻塞: PID {wlock[0]} ({wlock[1]})")
                    print(f"    查询: {wlock[4]}")
                    print(f"  阻塞者: PID {wlock[2]} ({wlock[3]})")
                    print(f"    查询: {wlock[5]}")
                    print()
            else:
                print("\n⚠️  正在等待的锁: 无")
            
            # 显示长时间运行的事务
            long_transactions = data["long_transactions"]
            if long_transactions:
                print(f"\n⏱️  长时间运行的事务 ({len(long_transactions)} 个):")
                for tx in long_transactions:
                    print(f"  PID {tx[0]} | {tx[1]} | {tx[2]} | {tx[3]}")
                    print(f"    事务时长: {tx[4]:.1f}秒 | 查询时长: {tx[5]:.1f}秒")
                    print(f"    查询: {tx[6]}")
                    if tx[4] > 60:  # 超过1分钟
                        print(f"    ⚠️  警告: 事务运行时间过长！")
                    print()
            else:
                print("\n⏱️  长时间运行的事务: 无")
            
            # 建议
            if waiting_locks:
                print("\n💡 建议:")
                print("  ⚠️  检测到锁等待，可能影响并发性能")
                print("  - 检查是否有多个任务更新同一行")
                print("  - 考虑优化事务大小")
                print("  - 检查是否有死锁")
            
            if long_transactions:
                print("\n💡 建议:")
                print("  ⚠️  检测到长时间运行的事务")
                print("  - 检查是否有慢查询")
                print("  - 考虑添加索引")
                print("  - 检查是否有未提交的事务")
            
            print("-" * 80)
            
            # 等待5秒
            await asyncio.sleep(5)
            
    except KeyboardInterrupt:
        print("\n\n监控已停止")

if __name__ == "__main__":
    asyncio.run(monitor())

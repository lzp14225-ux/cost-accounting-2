"""
NCTimeAgent - NC时间计算Agent
负责人：人员B1

职责：
1. 调用外部 NC Agent 获取每个子图的 NC 时间数据
2. 解析 NC 返回的 JSON 数据
3. 将时间数据写入 subgraphs 表（nc_roughing_time, nc_milling_time, drilling_time）
4. 将详细时间数据写入 features 表（nc_time_cost 字段）
"""
from typing import Dict, Any, List
import asyncio
import httpx
import re
import os
import json
import time
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy import select, update
from .base_agent import BaseAgent
from shared.database import get_db
from shared.models import Job, Subgraph, Feature

class NCTimeAgent(BaseAgent):
    """
    NC时间计算Agent
    调用外部统一NC Agent计算钻孔、开粗、精铣时间
    """
    
    def __init__(self, nc_agent_url: str = None, progress_publisher=None):
        super().__init__("NCTimeAgent")
        self.nc_agent_url = nc_agent_url or os.environ["NC_AGENT_URL"]
        self.timeout = int(os.environ["NC_AGENT_TIMEOUT"])
        self.request_timeout = int(os.environ["NC_AGENT_REQUEST_TIMEOUT"])
        self.poll_interval = float(os.environ["NC_AGENT_POLL_INTERVAL"])
        self.progress_publisher = progress_publisher
        self.logs_root = Path("logs")
        self.nc_log_retention_days = int(os.getenv("NC_LOG_RETENTION_DAYS", "7"))
        self.nc_log_cleanup_interval_days = int(os.getenv("NC_LOG_CLEANUP_INTERVAL_DAYS", "7"))
        self.nc_log_cleanup_state_file = self.logs_root / ".nc_log_cleanup_state.json"
        self.logger.info(
            f"[NCTimeAgent] initialized: url={self.nc_agent_url}, "
            f"workflow_timeout={self.timeout}s, request_timeout={self.request_timeout}s, "
            f"poll_interval={self.poll_interval}s"
        )

    async def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理NC时间计算
        
        Args:
            context: {
                "job_id": "任务ID",
                "dwg_file_path": "DWG文件路径（MinIO路径或本地路径）",
                "prt_file_path": "PRT文件路径（MinIO路径或本地路径）"
            }
        
        Returns:
            {
                "status": "ok" | "error",
                "message": "消息",
                "summary": {
                    "total_subgraphs": 总子图数,
                    "success_count": 成功数,
                    "failed_count": 失败数
                }
            }
        """
        job_id = context.get("job_id")
        if not job_id:
            return {"status": "error", "message": "缺少 job_id 参数"}
        
        self.logger.info(f"[NCTimeAgent] 开始处理 NC 时间计算: job_id={job_id}")
        
        # 发布进度：NC 时间计算开始
        self._maybe_cleanup_nc_log_files()
        self._maybe_cleanup_nc_log_files()
        if self.progress_publisher:
            from shared.progress_stages import ProgressStage, ProgressPercent
            self.progress_publisher.publish_progress(
                job_id=job_id,
                stage=ProgressStage.NC_CALCULATION_STARTED,
                progress=ProgressPercent.NC_CALCULATION_STARTED,
                message="NC 时间计算开始",
                details={"nc_agent_url": self.nc_agent_url}
            )
        
        # 临时文件列表（用于清理）
        temp_files = []
        
        try:
            # 1. 获取文件路径（如果是 MinIO 路径，需要先下载）
            dwg_file_path = context.get("dwg_file_path")
            prt_file_path = context.get("prt_file_path")
            
            if not dwg_file_path or not prt_file_path:
                return {"status": "error", "message": "缺少 dwg_file_path 或 prt_file_path 参数"}
            
            # 检查是否为 MinIO 路径（不以 / 或盘符开头）
            dwg_local_path = await self._ensure_local_file(dwg_file_path, job_id, "dwg")
            prt_local_path = await self._ensure_local_file(prt_file_path, job_id, "prt")
            
            if dwg_local_path != dwg_file_path:
                temp_files.append(dwg_local_path)
            if prt_local_path != prt_file_path:
                temp_files.append(prt_local_path)
            
            # 2. 调用外部 NC Agent
            nc_result = await self.call_nc_agent_workflow(
                job_id=job_id,
                dwg_file=dwg_local_path,
                prt_file=prt_local_path
            )

            fail_itemcodes = self._extract_fail_itemcodes(nc_result)
            await self._save_nc_failed_itemcodes(job_id, fail_itemcodes)
            
            code = nc_result.get("code")
            message = nc_result.get("message", "")
            
            # 检查返回码
            # 200: 完全成功
            # 206: 部分成功（某些子图失败，但有部分结果可用）
            # 500: 完全失败
            if code == 500:
                error_msg = nc_result.get("message", "NC Agent 调用失败")
                self.logger.error(f"[NCTimeAgent] NC Agent 完全失败: {error_msg}")
                
                # 发布失败进度
                if self.progress_publisher:
                    from shared.progress_stages import ProgressStage, ProgressPercent
                    self.progress_publisher.publish_progress(
                        job_id=job_id,
                        stage=ProgressStage.NC_CALCULATION_FAILED,
                        progress=ProgressPercent.NC_CALCULATION_STARTED,
                        message=f"NC 时间计算失败: {error_msg}",
                        details={"error": error_msg, "code": 500}
                    )
                
                return {"status": "error", "message": error_msg}
            elif code == 206:
                self.logger.warning(f"[NCTimeAgent] NC Agent 部分成功: {message}")
                # 继续处理，但记录警告
            elif code == 200:
                self.logger.info(f"[NCTimeAgent] NC Agent 完全成功: {message}")
            else:
                self.logger.warning(f"[NCTimeAgent] NC Agent 返回未知代码 {code}: {message}")
            
            # 3. 解析 NC 返回的数据
            json_output = nc_result.get("data", {}).get("json_output", {})
            if not json_output:
                # 提取更详细的错误信息
                error_details = nc_result.get("data", {}).get("error_details", "未知错误")
                failed_step = nc_result.get("data", {}).get("failed_at_step", "未知步骤")
                
                self.logger.warning(f"[NCTimeAgent] NC Agent 返回空数据")
                self.logger.warning(f"[NCTimeAgent] 失败步骤: Step {failed_step}")
                self.logger.warning(f"[NCTimeAgent] 错误详情: {error_details[:500]}")  # 只显示前500字符
                
                # 发布失败进度
                if self.progress_publisher:
                    from shared.progress_stages import ProgressStage, ProgressPercent
                    self.progress_publisher.publish_progress(
                        job_id=job_id,
                        stage=ProgressStage.NC_CALCULATION_FAILED,
                        progress=ProgressPercent.NC_CALCULATION_STARTED,
                        message=f"NC 时间计算失败: NC Agent 返回空数据 (Step {failed_step})",
                        details={
                            "error": f"NC Agent 返回空数据 (Step {failed_step})",
                            "failed_step": failed_step,
                            "error_details": error_details[:500] if error_details else "未知错误"
                        }
                    )
                
                return {
                    "status": "error", 
                    "message": f"NC Agent 处理失败 (Step {failed_step})",
                    "details": {
                        "failed_step": failed_step,
                        "error": error_details[:500] if error_details else "未知错误"
                    }
                }
            
            # ========== 打印 NC Agent 返回的原始数据 ==========
            self.logger.info(f"[NCTimeAgent] ========================================")
            self.logger.info(f"[NCTimeAgent] NC Agent 返回数据（原始）")
            self.logger.info(f"[NCTimeAgent] 子图总数: {len(json_output)}")
            self.logger.info(f"[NCTimeAgent] ========================================")
            
            for subgraph_name, subgraph_data in json_output.items():
                self.logger.info(f"[NCTimeAgent] ")
                self.logger.info(f"[NCTimeAgent] 子图: {subgraph_name}")
                operations = subgraph_data.get("operations", [])
                self.logger.info(f"[NCTimeAgent] 操作数量: {len(operations)}")
                
                for op in operations:
                    op_name = op.get("operation_name", "")
                    params = op.get("parameters", [])
                    
                    # 查找 id=124 的参数（Toolpath Time）
                    time_param = next((p for p in params if p.get("id") == 124), None)
                    
                    if time_param:
                        time_value = time_param.get("value", 0)
                        display_name = time_param.get("display_name", "")
                        self.logger.info(
                            f"[NCTimeAgent]   操作: {op_name} | "
                            f"时间: {time_value} | "
                            f"参数: id={time_param.get('id')}, {display_name}"
                        )
                    else:
                        self.logger.warning(f"[NCTimeAgent]   操作: {op_name} | 未找到 id=124 的时间参数")
            
            self.logger.info(f"[NCTimeAgent] ========================================")
            
            # 4. 处理每个子图的数据
            success_count = 0
            failed_count = 0
            
            for subgraph_name, subgraph_data in json_output.items():
                try:
                    # 提取子图 ID（例如：PH-01-M250297-P5.json -> PH-01）
                    subgraph_short_id = self._extract_subgraph_id(subgraph_name)
                    
                    # 查找对应的 subgraph_id（完整ID）
                    subgraph_id = await self._find_subgraph_id(job_id, subgraph_short_id)
                    
                    if not subgraph_id:
                        self.logger.warning(
                            f"[NCTimeAgent] 未找到子图映射: {subgraph_name} -> {subgraph_short_id}"
                        )
                        failed_count += 1
                        continue
                    
                    # ========== 保存子图的原始响应数据 ==========
                    await self._save_subgraph_response(job_id, subgraph_id, subgraph_name, subgraph_data)
                    
                    # 提取体积数据
                    volume_data = subgraph_data.get("batch_meta", {}).get("volume_data", {})
                    
                    # 解析操作数据（传入体积数据）
                    operations = subgraph_data.get("operations", [])
                    time_data = self._parse_operations(operations, volume_data)
                    
                    # 写入数据库
                    await self._save_nc_time_data(subgraph_id, time_data)
                    
                    success_count += 1
                    self.logger.info(
                        f"[NCTimeAgent] 成功处理子图: {subgraph_name} -> {subgraph_id}"
                    )
                    
                except Exception as e:
                    self.logger.error(
                        f"[NCTimeAgent] 处理子图失败: {subgraph_name}, error={e}",
                        exc_info=True
                    )
                    failed_count += 1
            
            # 5. 返回结果
            total_count = success_count + failed_count
            self.logger.info(
                f"[NCTimeAgent] NC 时间计算完成: "
                f"total={total_count}, success={success_count}, failed={failed_count}"
            )
            
            # 发布进度：NC 时间计算完成
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.NC_CALCULATION_COMPLETED,
                    progress=ProgressPercent.NC_CALCULATION_COMPLETED,
                    message=f"NC 时间计算完成，成功 {success_count}/{total_count}",
                    details={
                        "total_subgraphs": total_count,
                        "success_count": success_count,
                        "failed_count": failed_count
                    }
                )
            
            return {
                "status": "ok",
                "message": f"NC 时间计算完成，成功 {success_count}/{total_count}",
                "summary": {
                    "total_subgraphs": total_count,
                    "success_count": success_count,
                    "failed_count": failed_count
                }
            }
            
        except Exception as e:
            self.logger.error(f"[NCTimeAgent] NC 时间计算失败: {e}", exc_info=True)
            
            # 发布进度：NC 时间计算失败
            if self.progress_publisher:
                from shared.progress_stages import ProgressStage, ProgressPercent
                self.progress_publisher.publish_progress(
                    job_id=job_id,
                    stage=ProgressStage.NC_CALCULATION_FAILED,
                    progress=ProgressPercent.NC_CALCULATION_STARTED,
                    message=f"NC 时间计算失败: {str(e)}",
                    details={"error": str(e)}
                )
            
            return {"status": "error", "message": f"NC 时间计算失败: {str(e)}"}
        
        finally:
            # 清理临时文件
            await self._cleanup_temp_files(temp_files)
    
    async def call_nc_agent_workflow(
        self,
        job_id: str,
        dwg_file: str = None,
        prt_file: str = None
    ) -> Dict[str, Any]:
        """Call NC Agent using submit/status/result workflow API."""
        self.logger.info(f"[NCTimeAgent] calling NC workflow API: {self.nc_agent_url}")

        if not prt_file or not dwg_file:
            raise ValueError("Missing required nc input files: prt_file/dwg_file")

        files: Dict[str, Any] = {}
        try:
            dwg_ext = os.path.splitext(dwg_file)[1].lower()
            prt_ext = os.path.splitext(prt_file)[1].lower()

            files["prt_file"] = (f"model{prt_ext}", open(prt_file, "rb"), "application/octet-stream")
            drawing_field = "dxf_file" if dwg_ext == ".dxf" else "dwg_file"
            files[drawing_field] = (f"drawing{dwg_ext}", open(dwg_file, "rb"), "application/octet-stream")

            data = {
                "skip_approval": "true",
                "auto_continue": "true"
            }

            self.logger.info(
                f"[NCTimeAgent] submit files: prt={prt_file}, {drawing_field}={dwg_file}, "
                f"workflow_timeout={self.timeout}s, request_timeout={self.request_timeout}s"
            )

            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                submit_payload = await self._submit_nc_workflow(client, files, data)
                task_id = submit_payload.get("task_id")
                if not task_id:
                    raise RuntimeError(f"NC submit missing task_id: {submit_payload}")

                self.logger.info(
                    f"[NCTimeAgent] NC task submitted: task_id={task_id}, "
                    f"status={submit_payload.get('status')}, trace_id={submit_payload.get('trace_id')}"
                )

                await self._wait_for_nc_workflow(client, task_id)
                result = await self._fetch_nc_result(client, task_id)
                self._save_nc_debug_response(job_id, result)
                return result
        finally:
            for file_tuple in files.values():
                if len(file_tuple) > 1 and hasattr(file_tuple[1], "close"):
                    file_tuple[1].close()

    async def _submit_nc_workflow(
        self,
        client: httpx.AsyncClient,
        files: Dict[str, Any],
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        response = await client.post(
            f"{self.nc_agent_url}/api/v1/workflow/3d/submit",
            files=files,
            data=data
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"NC submit failed: {payload.get('message') or payload}")
        return payload

    async def _wait_for_nc_workflow(self, client: httpx.AsyncClient, task_id: str):
        deadline = time.monotonic() + self.timeout
        last_status = None
        last_message = ""

        while time.monotonic() < deadline:
            response = await client.get(f"{self.nc_agent_url}/api/v1/workflow/3d/status/{task_id}")
            response.raise_for_status()
            payload = response.json()

            status = payload.get("status")
            message = payload.get("message", "")
            if status != last_status:
                self.logger.info(
                    f"[NCTimeAgent] NC status: task_id={task_id}, status={status}, message={message}"
                )
                last_status = status
            last_message = message

            if status == "success":
                return

            if status == "failed":
                raise RuntimeError(f"NC workflow failed: {self._extract_nc_error_message(payload)}")

            if status not in {"queued", "running"}:
                raise RuntimeError(f"NC workflow returned unknown status: {status}, payload={payload}")

            await asyncio.sleep(self.poll_interval)

        raise RuntimeError(
            f"NC workflow timeout: task_id={task_id}, timeout={self.timeout}s, "
            f"last_status={last_status}, last_message={last_message}"
        )

    async def _fetch_nc_result(self, client: httpx.AsyncClient, task_id: str) -> Dict[str, Any]:
        response = await client.get(f"{self.nc_agent_url}/api/v1/workflow/3d/result/{task_id}")
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        if status == "failed" or payload.get("success") is False:
            raise RuntimeError(f"NC result failed: {self._extract_nc_error_message(payload)}")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"NC result payload invalid: {payload}")

        self.logger.info(
            f"[NCTimeAgent] NC result fetched: task_id={task_id}, status={status}, "
            f"code={result.get('code')}, message={result.get('message')}"
        )
        return result

    def _extract_nc_error_message(self, payload: Dict[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("error_message") or error.get("message") or payload.get("message") or str(payload)
        return payload.get("message") or str(error) or str(payload)

    def _save_nc_debug_response(self, job_id: str, result: Dict[str, Any]):
        debug_dir = Path("logs") / "nc_agent_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        debug_file = debug_dir / f"response_{job_id}_{timestamp}.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        self.logger.info(f"[NCTimeAgent] debug response saved: {debug_file}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def call_nc_agent(
        self,
        job_id: str,
        dwg_file: str = None,
        prt_file: str = None
    ) -> Dict[str, Any]:
        """
        调用外部 NC Agent (NC 3D Workflow API)
        
        Args:
            job_id: 任务ID
            dwg_file: DWG文件路径（保持原始格式）
            prt_file: PRT文件路径
        
        Returns:
            NC Agent 返回的 JSON 数据
        """
        self.logger.info(f"[NCTimeAgent] 调用 NC Agent: {self.nc_agent_url}")
        
        if not prt_file or not dwg_file:
            raise ValueError("必须提供 prt_file 和 dwg_file 路径")
        
        # 准备文件上传
        files = {}
        try:
            # 获取原始文件扩展名
            import os
            dwg_ext = os.path.splitext(dwg_file)[1]  # .dwg 或 .dxf
            prt_ext = os.path.splitext(prt_file)[1]  # .prt
            
            # 使用原始文件名和扩展名
            files['prt_file'] = (f'model{prt_ext}', open(prt_file, 'rb'), 'application/octet-stream')
            files['dxf_file'] = (f'drawing{dwg_ext}', open(dwg_file, 'rb'), 'application/octet-stream')
            
            # 准备表单数据
            data = {
                'skip_approval': 'true',
                'auto_continue': 'true'
            }
            
            self.logger.info(f"[NCTimeAgent] 上传文件并等待处理完成: prt={prt_file}, dwg={dwg_file}")
            self.logger.info(f"[NCTimeAgent] 超时设置: {self.timeout}秒")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.nc_agent_url}/api/v1/workflow/3d/run",
                    files=files,
                    data=data
                )
                response.raise_for_status()
                result = response.json()
                
                # 记录返回的 code
                code = result.get("code")
                message = result.get("message", "")
                self.logger.info(f"[NCTimeAgent] NC Agent 返回: code={code}, message={message}")
                
                # 详细记录响应结构（用于调试）
                import json
                data_obj = result.get("data", {})
                self.logger.info(f"[NCTimeAgent] 响应结构详情:")
                self.logger.info(f"  - data 存在: {data_obj is not None}")
                self.logger.info(f"  - data 类型: {type(data_obj)}")
                if data_obj:
                    self.logger.info(f"  - task_id: {data_obj.get('task_id')}")
                    self.logger.info(f"  - execution_time: {data_obj.get('execution_time')}")
                    self.logger.info(f"  - output_dir: {data_obj.get('output_dir')}")
                    self.logger.info(f"  - steps_completed: {data_obj.get('steps_completed')}")
                    self.logger.info(f"  - failed_at_step: {data_obj.get('failed_at_step')}")
                    
                    json_output = data_obj.get("json_output")
                    self.logger.info(f"  - json_output 存在: {json_output is not None}")
                    self.logger.info(f"  - json_output 类型: {type(json_output)}")
                    if json_output and isinstance(json_output, dict):
                        self.logger.info(f"  - json_output 子图数量: {len(json_output)}")
                        self.logger.info(f"  - json_output 子图列表: {list(json_output.keys())[:5]}")  # 只显示前5个
                    
                    # 如果有错误详情，记录下来
                    error_details = data_obj.get("error_details")
                    if error_details:
                        self.logger.warning(f"  - error_details: {error_details[:500]}")
                
                # 保存完整响应到文件（用于调试）
                try:
                    from pathlib import Path
                    from datetime import datetime
                    debug_dir = Path("logs") / "nc_agent_debug"
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    debug_file = debug_dir / f"response_{job_id}_{timestamp}.json"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    self.logger.info(f"[NCTimeAgent] 完整响应已保存: {debug_file}")
                except Exception as e:
                    self.logger.warning(f"[NCTimeAgent] 保存响应文件失败: {e}")
                
                return result
                
        finally:
            # 关闭文件句柄
            for file_tuple in files.values():
                if len(file_tuple) > 1 and hasattr(file_tuple[1], 'close'):
                    file_tuple[1].close()

    def _maybe_cleanup_nc_log_files(self):
        """Clean NC log json files on a fixed interval."""
        if self.nc_log_retention_days <= 0 or self.nc_log_cleanup_interval_days <= 0:
            self.logger.info(
                "[NCTimeAgent] Skip NC log cleanup: "
                f"retention_days={self.nc_log_retention_days}, "
                f"cleanup_interval_days={self.nc_log_cleanup_interval_days}"
            )
            return

        now_ts = time.time()
        interval_seconds = self.nc_log_cleanup_interval_days * 24 * 60 * 60

        try:
            last_cleanup_ts = self._load_nc_log_cleanup_state()
            if last_cleanup_ts and now_ts - last_cleanup_ts < interval_seconds:
                return

            cutoff_ts = now_ts - (self.nc_log_retention_days * 24 * 60 * 60)
            deleted_files = 0
            deleted_files += self._cleanup_json_files(self.logs_root / "nc_agent_debug", cutoff_ts)
            deleted_files += self._cleanup_json_files(self.logs_root / "nc_responses", cutoff_ts)
            self._write_nc_log_cleanup_state(now_ts)
            self.logger.info(
                "[NCTimeAgent] NC log cleanup completed: "
                f"deleted_files={deleted_files}, retention_days={self.nc_log_retention_days}, "
                f"cleanup_interval_days={self.nc_log_cleanup_interval_days}"
            )
        except Exception as e:
            self.logger.warning(f"[NCTimeAgent] NC log cleanup failed: {e}")

    def _load_nc_log_cleanup_state(self) -> float:
        if not self.nc_log_cleanup_state_file.exists():
            return 0.0

        try:
            state = json.loads(self.nc_log_cleanup_state_file.read_text(encoding="utf-8"))
            return float(state.get("last_cleanup_ts", 0.0))
        except Exception as e:
            self.logger.warning(f"[NCTimeAgent] Failed to read cleanup state: {e}")
            return 0.0

    def _write_nc_log_cleanup_state(self, timestamp: float):
        self.logs_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_cleanup_ts": timestamp,
            "last_cleanup_at": datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "retention_days": self.nc_log_retention_days,
            "cleanup_interval_days": self.nc_log_cleanup_interval_days,
        }
        self.nc_log_cleanup_state_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _cleanup_json_files(self, root_dir: Path, cutoff_ts: float) -> int:
        if not root_dir.exists():
            return 0

        deleted_files = 0
        for file_path in root_dir.rglob("*.json"):
            try:
                if file_path.stat().st_mtime < cutoff_ts:
                    file_path.unlink()
                    deleted_files += 1
            except FileNotFoundError:
                continue
            except Exception as e:
                self.logger.warning(f"[NCTimeAgent] Failed to delete expired log file {file_path}: {e}")

        directories = [path for path in root_dir.rglob("*") if path.is_dir()]
        directories.sort(key=lambda path: len(path.parts), reverse=True)
        for directory in directories:
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                continue

        return deleted_files

    def _extract_subgraph_id(self, subgraph_name: str) -> str:
        """
        从子图名称中提取短ID
        
        例如：
        - PH-01-M250297-P5.json -> PH-01
        - PU-06-M250297-P5.json -> PU-06
        
        Args:
            subgraph_name: 子图名称
        
        Returns:
            短ID（如 PH-01）
        """
        # 移除 .json 后缀
        name = subgraph_name.replace(".json", "")
        
        # 提取前两段（例如：PH-01）
        parts = name.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        
        return name
    
    async def _find_subgraph_id(self, job_id: str, short_id: str) -> str:
        """
        根据短ID查找完整的 subgraph_id
        
        Args:
            job_id: 任务ID
            short_id: 短ID（如 PH-01）
        
        Returns:
            完整的 subgraph_id（如 2cd0b581-f2b9-481d-a2fd-33074f57ebd4_PH-01）
        """
        import uuid
        job_uuid = uuid.UUID(job_id)
        
        async for db in get_db():
            # 查询所有子图
            result = await db.execute(
                select(Subgraph.subgraph_id)
                .where(Subgraph.job_id == job_uuid)
            )
            subgraph_ids = [row[0] for row in result.fetchall()]
            
            # 查找匹配的子图ID（以 short_id 结尾）
            for subgraph_id in subgraph_ids:
                if subgraph_id.endswith(f"_{short_id}") or subgraph_id == short_id:
                    return subgraph_id
            
            break
        
        return None
    
    async def _ensure_local_file(self, file_path: str, job_id: str, file_type: str) -> str:
        """
        确保文件在本地文件系统中
        
        如果是 MinIO 路径，下载到临时目录
        如果是本地路径，直接返回
        
        Args:
            file_path: 文件路径（MinIO 或本地）
            job_id: 任务ID
            file_type: 文件类型（dwg 或 prt）
        
        Returns:
            本地文件路径
        """
        import tempfile
        from pathlib import Path
        
        # 判断是否为本地路径（以 / 或盘符开头，如 C:）
        if file_path.startswith('/') or (len(file_path) > 1 and file_path[1] == ':'):
            # 本地路径，检查文件是否存在
            if Path(file_path).exists():
                self.logger.info(f"[NCTimeAgent] 使用本地文件: {file_path}")
                return file_path
            else:
                raise FileNotFoundError(f"本地文件不存在: {file_path}")
        
        # MinIO 路径，需要下载
        self.logger.info(f"[NCTimeAgent] 检测到 MinIO 路径，开始下载: {file_path}")
        
        try:
            from scripts.minio_client import MinIOClient
            
            # 创建 MinIO 客户端
            minio_client = MinIOClient()
            
            # 创建临时目录
            temp_dir = Path(tempfile.gettempdir()) / "nc_agent" / job_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成本地文件名
            file_ext = Path(file_path).suffix
            local_file = temp_dir / f"{file_type}{file_ext}"
            
            # 下载文件（使用正确的方法名 get_file）
            success = minio_client.get_file(file_path, str(local_file))
            
            if not success:
                raise Exception(f"从 MinIO 下载文件失败: {file_path}")
            
            self.logger.info(f"[NCTimeAgent] 文件下载成功: {file_path} -> {local_file}")
            return str(local_file)
            
        except Exception as e:
            self.logger.error(f"[NCTimeAgent] 处理文件失败: {file_path}, error={e}")
            raise
    
    async def _cleanup_temp_files(self, temp_files: List[str]):
        """
        清理临时文件
        
        Args:
            temp_files: 临时文件路径列表
        """
        if not temp_files:
            return
        
        import os
        from pathlib import Path
        
        for file_path in temp_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.logger.debug(f"[NCTimeAgent] 已删除临时文件: {file_path}")
                    
                    # 尝试删除空的临时目录
                    parent_dir = Path(file_path).parent
                    if parent_dir.exists() and not list(parent_dir.iterdir()):
                        parent_dir.rmdir()
                        self.logger.debug(f"[NCTimeAgent] 已删除空目录: {parent_dir}")
                        
            except Exception as e:
                self.logger.warning(f"[NCTimeAgent] 清理临时文件失败: {file_path}, error={e}")
    
    async def _save_subgraph_response(
        self, 
        job_id: str, 
        subgraph_id: str, 
        subgraph_name: str, 
        subgraph_data: Dict[str, Any]
    ):
        """
        保存单个子图的 NC Agent 响应数据到本地文件
        
        Args:
            job_id: 任务ID
            subgraph_id: 子图完整ID（如 2cd0b581-f2b9-481d-a2fd-33074f57ebd4_PH-01）
            subgraph_name: 子图文件名（如 PH-01-M250297-P5.json）
            subgraph_data: 子图的 NC 数据
        """
        import json
        from pathlib import Path
        from datetime import datetime
        
        try:
            # 创建保存目录：logs/nc_responses/job_id/subgraphs/
            save_dir = Path("logs") / "nc_responses" / job_id / "subgraphs"
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # 提取子图短ID（如 PH-01）
            subgraph_short_id = self._extract_subgraph_id(subgraph_name)
            
            # 构建子图数据结构
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            data = {
                "job_id": job_id,
                "subgraph_id": subgraph_id,
                "subgraph_short_id": subgraph_short_id,
                "file_name": subgraph_name,
                "timestamp": timestamp,
                "meta_data": subgraph_data.get("meta_data", {}),
                "operations": subgraph_data.get("operations", [])
            }
            
            # 保存为单独的 JSON 文件
            filename = f"{subgraph_short_id}_{timestamp}.json"
            filepath = save_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self.logger.debug(
                f"[NCTimeAgent] 保存子图数据: {subgraph_short_id} -> {filepath}"
            )
            
        except Exception as e:
            self.logger.error(
                f"[NCTimeAgent] 保存子图数据失败: {subgraph_name}, error={e}", 
                exc_info=True
            )
    
    async def _save_raw_response(self, job_id: str, nc_result: Dict[str, Any]):
        """
        保存 NC Agent 原始响应到本地文件（按子图保存）
        
        Args:
            job_id: 任务ID
            nc_result: NC Agent 返回的完整响应
        """
        import json
        from pathlib import Path
        from datetime import datetime
        
        try:
            # 创建保存目录：logs/nc_responses/job_id/
            save_dir = Path("logs") / "nc_responses" / job_id
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # 提取 json_output（包含所有子图数据）
            json_output = nc_result.get("data", {}).get("json_output", {})
            
            if not json_output:
                self.logger.warning(f"[NCTimeAgent] NC Agent 返回空数据，无法保存")
                return
            
            # 构建完整的数据结构（包含所有子图）
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            complete_data = {
                "job_id": job_id,
                "timestamp": timestamp,
                "task_id": nc_result.get("data", {}).get("task_id"),
                "execution_time": nc_result.get("data", {}).get("execution_time"),
                "total_subgraphs": len(json_output),
                "subgraphs": {}
            }
            
            # 遍历每个子图，保存详细数据
            for subgraph_name, subgraph_data in json_output.items():
                # 提取子图短ID（如 PH-01）
                subgraph_short_id = self._extract_subgraph_id(subgraph_name)
                
                # 保存子图数据
                complete_data["subgraphs"][subgraph_short_id] = {
                    "file_name": subgraph_name,
                    "meta_data": subgraph_data.get("meta_data", {}),
                    "operations": subgraph_data.get("operations", [])
                }
            
            # 保存为一个完整的 JSON 文件
            filename = f"nc_data_{job_id}_{timestamp}.json"
            filepath = save_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(complete_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(
                f"[NCTimeAgent] ✅ NC 数据已保存: {filepath} "
                f"(包含 {len(json_output)} 个子图)"
            )
            
        except Exception as e:
            self.logger.error(f"[NCTimeAgent] 保存 NC 数据失败: {e}", exc_info=True)
    
    def _parse_operations(self, operations: List[Dict[str, Any]], volume_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        解析操作数据，按面编码组织时间信息
        
        新规则（按面编码组织）：
        1. 面编码：使用业务实际编码 ["Z", "B", "C", "C_B", "Z_VIEW", "B_VIEW"]
        2. 钻孔：提取操作名格式为XX_XX_XX时取中间段，XX_ZXZ时取ZXZ
        3. 开粗：累加该面所有含"开粗"的操作Toolpath Time
        4. 精铣：分"半精""全精"两类，分别累加
        5. 空值约束：某面无任何加工类型时，details为空数组
        
        Args:
            operations: 操作列表
            volume_data: 体积数据（可选）
        
        Returns:
            {
                "nc_details": [
                    {"face_code": "Z", "details": [{"code": "开粗", "value": "150.0"}, ...]},
                    {"face_code": "B", "details": [...]},
                    ...
                ],
                "volume_mm3": 12345.678  # 体积（立方毫米）
            }
        """
        # 初始化6个面的数据结构（使用业务实际编码）
        face_codes = ["Z", "B", "C", "C_B", "Z_VIEW", "B_VIEW"]
        face_data = {face: {} for face in face_codes}  # {face_code: {code: total_time}}
        
        # 追踪当前面（只有遇到明确的面标识时才切换）
        current_face = "B_VIEW"  # 默认面
        
        for operation in operations:
            operation_name = operation.get("operation_name", "")
            
            # 提取 Toolpath Time（取 parameters 里面的第一个 value）
            time_value = self._extract_toolpath_time(operation)
            if time_value is None:
                continue
            
            # 判断加工类型
            process_code = None
            
            # 1. 检查操作名是否以面标识开头，如果是则切换当前面
            # 注意：必须先检查复合前缀（Z_VIEW_、B_VIEW_、C_B_），再检查单字母前缀（Z_、B_、X_）
            if "_" in operation_name:
                # 先检查复合前缀
                if operation_name.startswith("Z_VIEW_"):
                    current_face = "Z_VIEW"
                    if self._is_drilling_operation(operation_name):
                        process_code = self._extract_operation_code(operation_name)
                
                elif operation_name.startswith("B_VIEW_"):
                    current_face = "B_VIEW"
                    if self._is_drilling_operation(operation_name):
                        process_code = self._extract_operation_code(operation_name)
                
                elif operation_name.startswith("C_B_"):
                    current_face = "C_B"
                    if self._is_drilling_operation(operation_name):
                        process_code = self._extract_operation_code(operation_name)
                
                # 再检查单字母前缀
                else:
                    prefix = operation_name.split("_")[0]
                    
                    if prefix == "Z":
                        current_face = "Z"
                        if self._is_drilling_operation(operation_name):
                            process_code = self._extract_operation_code(operation_name)
                    
                    elif prefix == "B":
                        current_face = "B"
                        if self._is_drilling_operation(operation_name):
                            process_code = self._extract_operation_code(operation_name)
                    
                    elif prefix == "X":
                        current_face = "C"
                        if self._is_drilling_operation(operation_name):
                            process_code = self._extract_operation_code(operation_name)
            
            # 2. 检查是否包含"粗"字（开粗）- 归属到当前面
            if not process_code and "粗" in operation_name:
                process_code = "开粗"
            
            # 3. 检查是否包含"精"字（半精、全精）- 归属到当前面
            elif not process_code and "精" in operation_name:
                if "半精" in operation_name:
                    process_code = "半精"
                elif "全精" in operation_name:
                    process_code = "全精"
                else:
                    process_code = "精铣"
            
            # 如果没有匹配到任何类型，跳过
            if not process_code:
                self.logger.warning(f"[NCTimeAgent] 无法分类操作: {operation_name}")
                continue
            
            # 汇总到当前面和对应的代码
            if process_code not in face_data[current_face]:
                face_data[current_face][process_code] = Decimal("0")
            face_data[current_face][process_code] += time_value
        
        # 构建 nc_details（按面编码组织）
        nc_details = []
        
        for face_code in face_codes:
            details = []
            
            # 获取该面的所有加工类型
            face_processes = face_data[face_code]
            
            # 只添加有值的加工类型（不添加0值项）
            for code, value in face_processes.items():
                if value > 0:
                    details.append({
                        "code": code,
                        "value": value  # 保留原始浮点精度
                    })
            
            # 添加面数据（即使details为空也要添加）
            nc_details.append({
                "face_code": face_code,
                "details": details
            })
        
        result = {
            "nc_details": nc_details
        }
        
        # 添加体积数据（如果有）
        if volume_data:
            volume_mm3 = volume_data.get("volume_mm3")
            if volume_mm3 is not None:
                result["volume_mm3"] = volume_mm3
        
        return result
    
    def _extract_toolpath_time(self, operation: Dict[str, Any]) -> Decimal:
        """
        从操作中提取 Toolpath Time（取 parameters 里面的第一个 value）
        
        Args:
            operation: 操作数据
        
        Returns:
            时间值（分钟），如果未找到返回 None
        """
        parameters = operation.get("parameters", [])
        
        # 取第一个参数的 value（通常是 id=124 的 Toolpath Time）
        if parameters and len(parameters) > 0:
            first_param = parameters[0]
            value = first_param.get("value")
            if value is not None:
                return Decimal(str(value))
        
        return None
    
    def _is_drilling_operation(self, operation_name: str) -> bool:
        """
        判断是否为钻孔操作
        
        规则：
        1. XX_ZXZ 格式（如 Z_ZXZ）
        2. XX_XX_XX 格式（如 Z_M_A14, Z_L_A3, B_M1_A9, X_C_D17.0）
        
        Args:
            operation_name: 操作名称
        
        Returns:
            是否为钻孔操作
        """
        # 检查是否为 XX_ZXZ 格式
        if re.match(r"^[A-Z]+_ZXZ$", operation_name):
            return True
        
        # 检查是否为 XX_XX_XX 格式（中间部分是字母+可选数字的组合）
        # 例如：Z_M_A14, Z_L_A3, B_M1_A9, Z_C_A18, X_C_D17.0
        if re.match(r"^[A-Z]+_[A-Z]\d*_", operation_name):
            return True
        
        return False
    
    def _extract_operation_code(self, operation_name: str) -> str:
        """
        从操作名称中提取代码
        
        规则：
        1. 对于 XX_XX_XX 格式，提取中间的 XX（可能是字母+数字，如 M, L, M1, C）
        2. 对于 XX_ZXZ 格式，提取 ZXZ
        
        例如：
        - Z_M_A14 -> M
        - Z_L_A3 -> L
        - B_M1_A9 -> M1
        - Z_ZXZ -> ZXZ
        - Z_C_A18 -> C
        - X_C_D17.0 -> C
        
        Args:
            operation_name: 操作名称
        
        Returns:
            操作代码（如 M, L, M1, C, ZXZ）
        """
        # 检查是否为 XX_ZXZ 格式
        if re.match(r"^[A-Z]+_ZXZ$", operation_name):
            return "ZXZ"
        
        # 提取 XX_XX_XX 格式中间的 XX（字母+可选数字）
        # 例如：Z_M_A14 -> M, Z_M1_A18 -> M1, Z_C_A18 -> C, X_C_D17.0 -> C
        match = re.search(r"^[A-Z]+_([A-Z]\d*)_", operation_name)
        if match:
            return match.group(1)
        
        # 如果无法匹配，返回原始名称
        self.logger.warning(f"[NCTimeAgent] 无法提取操作代码: {operation_name}")
        return operation_name
    
    async def _save_nc_time_data(self, subgraph_id: str, time_data: Dict[str, Any]):
        """
        保存 NC 时间数据到数据库（只写入 features 表）
        
        Args:
            subgraph_id: 子图ID
            time_data: 时间数据，格式：
                {
                    "nc_details": [
                        {"face_code": "A", "details": [{"code": "开粗", "value": 150.0}, ...]},
                        ...
                    ],
                    "volume_mm3": 12345.678  # 可选
                }
        """
        async for db in get_db():
            # 转换 Decimal 类型为 float（JSON 序列化需要）
            def convert_decimals(obj):
                """递归转换 Decimal 为 float"""
                from decimal import Decimal
                if isinstance(obj, Decimal):
                    return float(obj)
                elif isinstance(obj, dict):
                    return {k: convert_decimals(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_decimals(item) for item in obj]
                return obj
            
            # 准备更新数据
            nc_time_cost_data = convert_decimals({"nc_details": time_data["nc_details"]})
            update_values = {
                "nc_time_cost": nc_time_cost_data,
                "created_at": datetime.utcnow()
            }
            
            # 如果有体积数据，也一起更新
            if "volume_mm3" in time_data:
                update_values["volume_mm3"] = (
                    float(time_data["volume_mm3"])
                    if isinstance(time_data["volume_mm3"], Decimal)
                    else time_data["volume_mm3"]
                )
            
            # 更新 features 表（nc_time_cost 和 volume_mm3 字段）
            await db.execute(
                update(Feature)
                .where(Feature.subgraph_id == subgraph_id)
                .values(**update_values)
            )
            
            await db.commit()
            
            self.logger.debug(
                f"[NCTimeAgent] 保存 NC 时间数据到 features 表: subgraph_id={subgraph_id}, "
                f"faces={len(time_data['nc_details'])}, "
                f"volume_mm3={time_data.get('volume_mm3', 'N/A')}"
            )
            
            break

    def _extract_fail_itemcodes(self, nc_result: Dict[str, Any]) -> List[str]:
        raw_codes = nc_result.get("fail_itemcode", [])
        if not isinstance(raw_codes, list):
            return []

        normalized_codes: List[str] = []
        seen = set()
        for code in raw_codes:
            text = str(code).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_codes.append(text)
        return normalized_codes

    async def _save_nc_failed_itemcodes(self, job_id: str, fail_itemcodes: List[str]):
        async for db in get_db():
            result = await db.execute(
                select(Job.meta_data).where(Job.job_id == job_id)
            )
            current_meta = result.scalar_one_or_none() or {}
            if not isinstance(current_meta, dict):
                current_meta = {}

            updated_meta = dict(current_meta)
            updated_meta["nc_failed_itemcodes"] = fail_itemcodes
            updated_meta["nc_failed_updated_at"] = datetime.utcnow().isoformat()

            await db.execute(
                update(Job)
                .where(Job.job_id == job_id)
                .values(meta_data=updated_meta)
            )
            await db.commit()

            self.logger.info(
                f"[NCTimeAgent] 保存 NC 识别失败物料编码: job_id={job_id}, count={len(fail_itemcodes)}"
            )
            break

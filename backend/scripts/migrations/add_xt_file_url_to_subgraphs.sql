-- 给 subgraphs 表增加 xt_file_url 字段
-- 存储 MinIO 中对应 .x_t 文件的路径，由拆图流程（cad_chaitu）写入
-- 格式：xt/{year}/{month}/{job_id}/{part_code}.x_t
ALTER TABLE subgraphs
    ADD COLUMN IF NOT EXISTS xt_file_url VARCHAR(500);

-- 给 jobs 表增加 prt_file_path 字段
-- 存储 MinIO 中 PRT 源文件路径，与 dwg_file_path 路径规则一致
-- 格式：prt/{year}/{month}/{job_id}/{source_filename}.prt
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS prt_file_path VARCHAR(500);

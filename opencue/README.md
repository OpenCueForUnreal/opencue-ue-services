# OpenCue + UE 云渲染集成

基于 OpenCue Python 包 (`pycue` + `pyoutline`) 实现 UE5 渲染任务调度。

## 快速开始

### 1. 安装 OpenCue 服务端

按照官方文档安装：
- [PostgreSQL](https://www.postgresql.org/download/windows/)
- [Cuebot](https://www.opencue.io/docs/getting-started/deploying-cuebot/)
- [RQD](https://www.opencue.io/docs/getting-started/installing-rqd/)

### 2. 安装 Python 包

```powershell
cd opencue-ue-services\opencue\jobs
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
cp ..\.env.example ..\.env
# 编辑 .env，设置 CUEBOT_HOST、UE_ROOT 等
```

### 4. 测试连接

```powershell
python test_connection.py
```

### 5. 提交 UE 渲染作业

```powershell
python ue_job_submitter.py --template Seq1 \
    --map-path /Game/Maps/Map0.Map0 \
    --level-sequence /Game/Seqs/Seq1.Seq1
```

## 目录结构

```
opencue/
├── .env.example          # 环境变量模板
├── README.md
└── jobs/
    ├── requirements.txt      # Python 依赖
    ├── outline_config.py     # 配置模块
    ├── test_connection.py    # 连接测试脚本
    └── ue_job_submitter.py   # UE 作业提交
```

## 参考文档

- [OpenCue 官方文档](https://www.opencue.io/docs/)
- [PyCue API](https://www.opencue.io/docs/getting-started/installing-pycue-and-pyoutline/)

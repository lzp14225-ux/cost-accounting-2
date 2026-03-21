import { Job, Message, InteractionCard } from '../store/useAppStore'

// 模拟任务数据
export const mockJobs: Job[] = [
  {
    id: 'job_001',
    status: 'completed',
    stage: '已完成',
    progress: 100,
    dwgFile: {
      id: 'dwg_001',
      name: 'mold_part_001.dwg',
      size: 2048576,
      type: 'application/acad',
    },
    prtFile: {
      id: 'prt_001',
      name: 'mold_part_001.prt',
      size: 1536000,
      type: 'application/x-prt',
    },
    totalCost: 1250.80,
    subgraphsCount: 5,
    createdAt: new Date('2024-01-10T09:30:00'),
    updatedAt: new Date('2024-01-10T10:45:00'),
  },
  {
    id: 'job_002',
    status: 'processing',
    stage: '特征识别',
    progress: 65,
    dwgFile: {
      id: 'dwg_002',
      name: 'injection_mold_base.dwg',
      size: 3145728,
      type: 'application/acad',
    },
    subgraphsCount: 8,
    createdAt: new Date('2024-01-10T11:15:00'),
    updatedAt: new Date('2024-01-10T11:45:00'),
  },
  {
    id: 'job_003',
    status: 'need_user_input',
    stage: '等待用户输入',
    progress: 40,
    dwgFile: {
      id: 'dwg_003',
      name: 'complex_mold.dwg',
      size: 4194304,
      type: 'application/acad',
    },
    prtFile: {
      id: 'prt_003',
      name: 'complex_mold.prt',
      size: 2097152,
      type: 'application/x-prt',
    },
    subgraphsCount: 12,
    createdAt: new Date('2024-01-10T08:20:00'),
    updatedAt: new Date('2024-01-10T09:10:00'),
  },
  {
    id: 'job_004',
    status: 'failed',
    stage: 'CAD解析',
    progress: 15,
    dwgFile: {
      id: 'dwg_004',
      name: 'corrupted_file.dwg',
      size: 1048576,
      type: 'application/acad',
    },
    errorMessage: 'CAD文件格式错误，无法解析',
    createdAt: new Date('2024-01-09T16:30:00'),
    updatedAt: new Date('2024-01-09T16:35:00'),
  },
  {
    id: 'job_005',
    status: 'failed',
    stage: 'CAD解析',
    progress: 15,
    dwgFile: {
      id: 'dwg_005',
      name: 'corrupted_file2.dwg',
      size: 1048576,
      type: 'application/acad',
    },
    errorMessage: 'CAD文件格式错误，无法解析',
    createdAt: new Date('2024-01-09T16:30:00'),
    updatedAt: new Date('2024-01-09T16:35:00'),
  }
]

// 模拟消息数据
export const mockMessages: Message[] = [
  {
    id: '1',
    type: 'assistant',
    content: '您好！我是模具成本核算AI助手。请上传您的DWG或PRT文件，我将帮您进行成本核算分析。\n\n支持的功能：\n- 📄 CAD文件解析\n- 🔍 特征自动识别\n- ⚙️ 工艺智能决策\n- 💰 成本精确计算\n- 📊 报表自动生成',
    timestamp: new Date('2024-01-10T12:00:00'),
  },
]

// 模拟交互卡片
export const mockInteractionCards: InteractionCard[] = [
  {
    id: 'card_001',
    type: 'missing_input',
    title: '缺少厚度参数',
    message: '子图UP01无法自动识别厚度信息，请手动输入以继续成本计算。',
    severity: 'error',
    jobId: 'job_003',
    fields: [
      {
        key: 'thickness_mm',
        label: '厚度 (mm)',
        component: 'number',
        required: true,
        defaultValue: 10,
        min: 1,
        max: 500,
        subgraphId: 'UP01',
      },
    ],
    buttons: [
      {
        key: 'submit',
        label: '提交并继续',
        style: 'primary',
      },
      {
        key: 're_recognize',
        label: '重新识别',
        style: 'default',
      },
    ],
  },
]

// 模拟API响应延迟
export const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// 生成随机ID
export const generateId = () => {
  const timestamp = Date.now().toString(36)
  const random = Math.random().toString(36).substr(2, 9)
  const counter = Math.floor(Math.random() * 1000).toString(36)
  return `${timestamp}_${random}_${counter}`
}

// 模拟文件上传进度
export const simulateUploadProgress = (
  onProgress: (progress: number) => void,
  duration: number = 3000
) => {
  let progress = 0
  const interval = 100
  const increment = (interval / duration) * 100

  const timer = setInterval(() => {
    progress += increment + Math.random() * 5
    progress = Math.min(progress, 95)
    onProgress(Math.round(progress))

    if (progress >= 95) {
      clearInterval(timer)
      // 最后跳到100%
      setTimeout(() => onProgress(100), 200)
    }
  }, interval)

  return timer
}

// 模拟任务进度更新
export const simulateJobProgress = (
  _jobId: string,
  onUpdate: (progress: { stage: string; progress: number; status: string }) => void
) => {
  const stages = [
    { stage: '初始化', progress: 5 },
    { stage: 'CAD解析', progress: 20 },
    { stage: '特征识别', progress: 50 },
    { stage: '工艺决策', progress: 70 },
    { stage: '价格计算', progress: 85 },
    { stage: '报表生成', progress: 95 },
    { stage: '已完成', progress: 100 },
  ]

  let currentStage = 0

  const updateProgress = () => {
    if (currentStage < stages.length) {
      const stage = stages[currentStage]
      onUpdate({
        stage: stage.stage,
        progress: stage.progress,
        status: stage.progress === 100 ? 'completed' : 'processing',
      })

      currentStage++
      
      if (currentStage < stages.length) {
        setTimeout(updateProgress, 2000 + Math.random() * 3000)
      }
    }
  }

  // 开始模拟
  setTimeout(updateProgress, 1000)
}
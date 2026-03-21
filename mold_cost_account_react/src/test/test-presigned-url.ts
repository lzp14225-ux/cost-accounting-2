// 测试预签名URL API调用
import { fileService } from '../services/fileService'

export const testPresignedUrl = async () => {
  const testFilePath = 'dxf/2026/01/9ba97078-a7bf-4472-a977-564dca64cee7/LP-01.dxf'
  
  // console.log('🧪 开始测试预签名URL API...')
  // console.log('测试文件路径:', testFilePath)
  
  try {
    const result = await fileService.getPresignedUrl(testFilePath, 3600)
    
    // console.log('✅ API调用成功')
    // console.log('返回结果:', result)
    // console.log('URL长度:', result.url?.length)
    // console.log('URL前100字符:', result.url?.substring(0, 100))
    
    return result
  } catch (error) {
    console.error('❌ API调用失败:', error)
    throw error
  }
}

// 在浏览器控制台中可以调用这个函数进行测试
// @ts-ignore
window.testPresignedUrl = testPresignedUrl
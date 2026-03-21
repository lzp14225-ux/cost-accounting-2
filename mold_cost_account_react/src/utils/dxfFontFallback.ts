// DXF字体回退方案

/**
 * 如果dxf-viewer不支持外部字体加载，这里提供一些备用方案
 */

/**
 * 检查浏览器是否支持字体加载API
 */
export function checkFontLoadingSupport(): boolean {
  return 'FontFace' in window && 'fonts' in document
}

/**
 * 尝试通过CSS @font-face加载SHX字体（可能不起作用，因为SHX不是Web字体格式）
 */
export async function loadSHXFontsAsCSS(): Promise<void> {
  // console.log('🔄 尝试通过CSS加载SHX字体...')
  
  const fontNames = [
    'hztxt', 'txt', 'romans', 'simplex', 'complex'
  ]
  
  for (const fontName of fontNames) {
    try {
      const fontUrl = `/fonts/${fontName}.shx`
      
      // 创建@font-face规则（可能不起作用）
      const style = document.createElement('style')
      style.textContent = `
        @font-face {
          font-family: '${fontName}';
          src: url('${fontUrl}') format('truetype');
        }
      `
      document.head.appendChild(style)
      
      // console.log(`✅ CSS字体规则添加: ${fontName}`)
    } catch (error) {
      // console.log(`⚠️ CSS字体规则失败: ${fontName}`, error)
    }
  }
}

/**
 * 检查DXF文件是否包含文本，并提供替代显示方案
 */
export function analyzeTextEntities(dxfData: any): {
  hasText: boolean
  textCount: number
  textEntities: any[]
  suggestions: string[]
} {
  const result = {
    hasText: false,
    textCount: 0,
    textEntities: [] as any[],
    suggestions: [] as string[]
  }
  
  try {
    if (dxfData && dxfData.entities) {
      const textEntities = dxfData.entities.filter((entity: any) => 
        entity.type === 'TEXT' || entity.type === 'MTEXT'
      )
      
      result.hasText = textEntities.length > 0
      result.textCount = textEntities.length
      result.textEntities = textEntities
      
      if (result.hasText) {
        result.suggestions.push('DXF文件包含文本，但可能因为字体问题无法显示')
        result.suggestions.push('建议：')
        result.suggestions.push('1. 检查DXF文件是否使用了标准字体')
        result.suggestions.push('2. 尝试在AutoCAD中重新保存，使用标准字体')
        result.suggestions.push('3. 考虑将文本转换为几何图形')
        
        // 分析使用的字体
        const usedFonts = new Set()
        textEntities.forEach((entity: any) => {
          if (entity.style) usedFonts.add(entity.style)
          if (entity.fontName) usedFonts.add(entity.fontName)
        })
        
        if (usedFonts.size > 0) {
          result.suggestions.push(`4. 文件使用的字体: ${Array.from(usedFonts).join(', ')}`)
        }
      }
    }
  } catch (error) {
    // console.log('⚠️ 分析文本实体失败:', error)
  }
  
  return result
}

/**
 * 显示字体问题的用户提示
 */
export function showFontIssueNotification(textAnalysis: ReturnType<typeof analyzeTextEntities>): void {
  if (textAnalysis.hasText) {
    // console.log('📝 DXF字体问题分析:')
    // console.log(`- 发现 ${textAnalysis.textCount} 个文本实体`)
    // console.log('- 建议解决方案:')
    textAnalysis.suggestions.forEach((suggestion, index) => {
      // console.log(`  ${index + 1}. ${suggestion}`)
    })
  }
}

/**
 * 尝试替代的文本渲染方案
 */
export function tryAlternativeTextRendering(viewer: any, dxfData: any): void {
  // console.log('🔄 尝试替代文本渲染方案...')
  
  try {
    // 方案1：尝试强制刷新渲染
    if (typeof viewer.Refresh === 'function') {
      viewer.Refresh()
      // console.log('✅ 执行Refresh')
    }
    
    if (typeof viewer.Redraw === 'function') {
      viewer.Redraw()
      // console.log('✅ 执行Redraw')
    }
    
    if (typeof viewer.Update === 'function') {
      viewer.Update()
      // console.log('✅ 执行Update')
    }
    
    // 方案2：尝试重新设置渲染选项
    if (typeof viewer.SetRenderMode === 'function') {
      viewer.SetRenderMode('wireframe')
      // console.log('✅ 设置线框模式')
    }
    
    // 方案3：尝试启用所有渲染选项
    const renderOptions = [
      'EnableText', 'enableText', 'ShowText', 'showText',
      'RenderText', 'renderText', 'DisplayText', 'displayText'
    ]
    
    for (const option of renderOptions) {
      if (typeof viewer[option] === 'function') {
        try {
          viewer[option](true)
          // console.log(`✅ 启用 ${option}`)
        } catch (e) {
          // console.log(`⚠️ ${option} 失败:`, e)
        }
      }
    }
    
  } catch (error) {
    // console.log('⚠️ 替代文本渲染失败:', error)
  }
}

/**
 * 生成字体问题报告
 */
export function generateFontReport(viewer: any, dxfData: any): string {
  const report = []
  
  report.push('=== DXF字体问题诊断报告 ===')
  report.push('')
  
  // 1. 浏览器字体支持
  report.push('1. 浏览器字体支持:')
  report.push(`   - FontFace API: ${checkFontLoadingSupport() ? '✅ 支持' : '❌ 不支持'}`)
  report.push('')
  
  // 2. DXF文本分析
  const textAnalysis = analyzeTextEntities(dxfData)
  report.push('2. DXF文本分析:')
  report.push(`   - 包含文本: ${textAnalysis.hasText ? '✅ 是' : '❌ 否'}`)
  report.push(`   - 文本数量: ${textAnalysis.textCount}`)
  if (textAnalysis.textEntities.length > 0) {
    report.push('   - 文本示例:')
    textAnalysis.textEntities.slice(0, 3).forEach((entity, index) => {
      report.push(`     ${index + 1}. "${entity.text || entity.textString || '无文本'}" (${entity.type})`)
    })
  }
  report.push('')
  
  // 3. 查看器方法检查
  report.push('3. 查看器字体方法:')
  const fontMethods = [
    'LoadFont', 'loadFont', 'AddFont', 'addFont',
    'SetFont', 'setFont', 'EnableText', 'enableText'
  ]
  
  fontMethods.forEach(method => {
    const available = typeof viewer[method] === 'function'
    report.push(`   - ${method}: ${available ? '✅ 可用' : '❌ 不可用'}`)
  })
  report.push('')
  
  // 4. 建议解决方案
  report.push('4. 建议解决方案:')
  if (textAnalysis.hasText) {
    textAnalysis.suggestions.forEach((suggestion, index) => {
      report.push(`   ${index + 1}. ${suggestion}`)
    })
  } else {
    report.push('   - DXF文件不包含文本，无需字体支持')
  }
  
  return report.join('\n')
}
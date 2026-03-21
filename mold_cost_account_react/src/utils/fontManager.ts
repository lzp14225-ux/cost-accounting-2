// DXF字体管理工具

/**
 * 常用的DXF字体列表
 */
export const COMMON_DXF_FONTS = [
  // 中文字体
  'hztxt.shx',
  'HZTXT.SHX', 
  'gbcbig.shx',
  'GBCBIG.SHX',
  'chineset.shx',
  'CHINESET.SHX',
  'CHINESE.SHX',
  'hztxt_e.shx',
  'Hztxt1.shx',
  'Hztxt2.shx',
  'HZTXT3.SHX',
  'HZTXTB.SHX',
  'HZTXTH.SHX',
  'HZTXTS.SHX',
  
  // 英文字体
  'txt.shx',
  'TXT.SHX',
  'romans.shx',
  'ROMANS.SHX',
  'simplex.shx',
  'SIMPLEX.SHX',
  'complex.shx',
  'COMPLEX.SHX',
  'romanc.shx',
  'ROMANC.SHX',
  'romand.shx',
  'ROMAND.SHX',
  'romant.shx',
  'ROMANT.SHX',
  
  // 其他常用字体
  'monotxt.shx',
  'MONOTXT.SHX',
  'italic.shx',
  'ITALIC.SHX',
  'gothice.shx',
  'GOTHICE.SHX',
  'gothicg.shx',
  'GOTHICG.SHX',
  'gothici.shx',
  'GOTHICI.SHX'
]

/**
 * 字体名称映射 - 处理大小写和扩展名问题
 */
export const FONT_NAME_MAP: Record<string, string> = {
  // 中文字体映射
  'hztxt': 'hztxt.shx',
  'HZTXT': 'HZTXT.SHX',
  'hztxt.shx': 'hztxt.shx',
  'HZTXT.SHX': 'HZTXT.SHX',
  'gbcbig': 'gbcbig.shx',
  'GBCBIG': 'GBCBIG.SHX',
  'gbcbig.shx': 'gbcbig.shx',
  'GBCBIG.SHX': 'GBCBIG.SHX',
  'chineset': 'chineset.shx',
  'CHINESET': 'CHINESET.SHX',
  'chineset.shx': 'chineset.shx',
  'CHINESET.SHX': 'CHINESET.SHX',
  'chinese': 'CHINESE.SHX',
  'CHINESE': 'CHINESE.SHX',
  'CHINESE.SHX': 'CHINESE.SHX',
  
  // 英文字体映射
  'txt': 'txt.shx',
  'TXT': 'TXT.SHX',
  'txt.shx': 'txt.shx',
  'TXT.SHX': 'TXT.SHX',
  'romans': 'romans.shx',
  'ROMANS': 'ROMANS.SHX',
  'romans.shx': 'romans.shx',
  'ROMANS.SHX': 'ROMANS.SHX',
  'simplex': 'simplex.shx',
  'SIMPLEX': 'SIMPLEX.SHX',
  'simplex.shx': 'simplex.shx',
  'SIMPLEX.SHX': 'SIMPLEX.SHX',
  'complex': 'complex.shx',
  'COMPLEX': 'COMPLEX.SHX',
  'complex.shx': 'complex.shx',
  'COMPLEX.SHX': 'COMPLEX.SHX'
}

/**
 * 获取字体文件的完整URL
 */
export function getFontUrl(fontName: string): string {
  // 规范化字体名称
  const normalizedName = FONT_NAME_MAP[fontName] || fontName
  
  // 确保有.shx扩展名
  const fontFileName = normalizedName.toLowerCase().endsWith('.shx') 
    ? normalizedName 
    : `${normalizedName}.shx`
  
  return `/fonts/${fontFileName}`
}

/**
 * 预加载字体文件
 */
export async function preloadFont(fontName: string): Promise<boolean> {
  try {
    const fontUrl = getFontUrl(fontName)
    const response = await fetch(fontUrl)
    
    if (response.ok) {
      return true
    } else {
      return false
    }
  } catch (error) {
    // console.log(`❌ 字体预加载失败: ${fontName}`, error)
    return false
  }
}

/**
 * 批量预加载常用字体
 */
export async function preloadCommonFonts(): Promise<string[]> {
  
  const loadedFonts: string[] = []
  
  for (const fontName of COMMON_DXF_FONTS) {
    const success = await preloadFont(fontName)
    if (success) {
      loadedFonts.push(fontName)
    }
  }
  
  return loadedFonts
}

/**
 * 从DXF实体中提取使用的字体
 */
export function extractUsedFonts(dxfData: any): string[] {
  const usedFonts = new Set<string>()
  
  try {
    if (dxfData && dxfData.entities) {
      dxfData.entities.forEach((entity: any) => {
        // 检查文本实体的字体
        if (entity.type === 'TEXT' || entity.type === 'MTEXT') {
          if (entity.style) {
            usedFonts.add(entity.style)
          }
          if (entity.fontName) {
            usedFonts.add(entity.fontName)
          }
          if (entity.textStyle) {
            usedFonts.add(entity.textStyle)
          }
        }
      })
      
      // 检查样式表中的字体
      if (dxfData.tables && dxfData.tables.style) {
        dxfData.tables.style.forEach((style: any) => {
          if (style.fontFile) {
            usedFonts.add(style.fontFile)
          }
          if (style.primaryFontFile) {
            usedFonts.add(style.primaryFontFile)
          }
        })
      }
    }
  } catch (error) {
    // console.log('⚠️ 提取字体信息失败:', error)
  }
  
  return Array.from(usedFonts)
}

/**
 * 配置DXF查看器的字体
 */
export async function configureDxfViewerFonts(viewer: any): Promise<void> {
  
  try {
    // 方法1：尝试设置字体路径
    if (typeof viewer.SetFontsPath === 'function') {
      viewer.SetFontsPath('/fonts/')
      // console.log('✅ 设置字体路径: /fonts/')
    } else if (typeof viewer.setFontsPath === 'function') {
      viewer.setFontsPath('/fonts/')
      // console.log('✅ 设置字体路径: /fonts/ (小写方法)')
    }
    
    // 方法2：尝试批量加载字体
    if (typeof viewer.LoadFont === 'function') {
      for (const fontName of COMMON_DXF_FONTS.slice(0, 10)) { // 只加载前10个常用字体
        try {
          const fontUrl = getFontUrl(fontName)
          await viewer.LoadFont(fontUrl)
          // console.log(`✅ 加载字体: ${fontName}`)
        } catch (fontError) {
          // console.log(`⚠️ 字体加载失败: ${fontName}`, fontError)
        }
      }
    } else if (typeof viewer.loadFont === 'function') {
      for (const fontName of COMMON_DXF_FONTS.slice(0, 10)) {
        try {
          const fontUrl = getFontUrl(fontName)
          await viewer.loadFont(fontUrl)
          // console.log(`✅ 加载字体: ${fontName}`)
        } catch (fontError) {
          // console.log(`⚠️ 字体加载失败: ${fontName}`, fontError)
        }
      }
    }
    
  } catch (error) {
    // console.log('❌ 配置DXF查看器字体失败:', error)
  }
}
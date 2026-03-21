// DXF Viewer 类型声明
declare module 'dxf-viewer' {
  interface DxfViewerOptions {
    canvasWidth?: number
    canvasHeight?: number
    autoResize?: boolean
    clearColor?: number | string | any  // 支持多种颜色格式
    clearAlpha?: number
    canvasAlpha?: boolean
    canvasPremultipliedAlpha?: boolean
    antialias?: boolean
    colorCorrection?: boolean
    blackWhiteInversion?: boolean
    pointSize?: number
    sceneOptions?: {
      arcTessellationAngle?: number
      minArcTessellationSubdivisions?: number
      wireframeMesh?: boolean
      suppressPaperSpace?: boolean
      textOptions?: {
        curveSubdivision?: number
        fallbackChar?: string
      }
    }
    retainParsedDxf?: boolean
    preserveDrawingBuffer?: boolean
    fileEncoding?: string
    [key: string]: any
  }

  interface LoadOptions {
    url: string
    fonts?: string[]
    progressCbk?: (phase: string, processedSize: number, totalSize: number) => void
  }

  class DxfViewer {
    constructor(domContainer: HTMLElement, options?: DxfViewerOptions)
    
    Load(options: string | LoadOptions): Promise<void>
    Clear(): void
    Destroy(): void
    FitView(): void
    Render(): void
    SetSize(width: number, height: number): void
    
    // 获取相关对象
    HasRenderer(): boolean
    GetRenderer(): any
    GetCanvas(): HTMLCanvasElement
    GetDxf(): any
    GetScene(): any
    GetCamera(): any
    GetOrigin(): any
    GetBounds(): any
    
    // 图层相关
    GetLayers(): any[]
    ShowLayer(layerName: string, show: boolean): void
    
    // 视图控制
    SetView(bounds: any): void
    
    // 事件相关
    Subscribe(event: string, callback: Function): void
    Unsubscribe(event: string, callback: Function): void
    
    // 静态属性
    static DefaultOptions: DxfViewerOptions
  }

  class DxfFetcher {
    // DxfFetcher 相关方法
  }

  export { DxfViewer, DxfFetcher }
}
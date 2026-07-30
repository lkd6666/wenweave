declare module 'gifsicle-wasm-browser' {
  interface GifsicleInput {
    file: Blob | File | ArrayBuffer | string
    name: string
  }

  interface GifsicleRunOptions {
    input: GifsicleInput[]
    command: string[]
    isStrict?: boolean
  }

  const gifsicle: {
    run(options: GifsicleRunOptions): Promise<File[]>
  }

  export default gifsicle
}

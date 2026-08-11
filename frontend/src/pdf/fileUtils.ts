export function isPdfFile(file: File): boolean {
  return /\.pdf$/i.test(file.name)
}

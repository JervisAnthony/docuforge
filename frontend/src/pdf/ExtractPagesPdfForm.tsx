import type { PdfFormProps } from './types'
import { PageSelectionPdfForm } from './PageSelectionPdfForm'

export function ExtractPagesPdfForm(props: PdfFormProps) {
  return <PageSelectionPdfForm operation="extract" {...props} />
}

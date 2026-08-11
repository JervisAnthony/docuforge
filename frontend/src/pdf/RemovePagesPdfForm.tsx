import type { PdfFormProps } from './types'
import { PageSelectionPdfForm } from './PageSelectionPdfForm'

export function RemovePagesPdfForm(props: PdfFormProps) {
  return <PageSelectionPdfForm operation="remove" {...props} />
}

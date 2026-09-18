import { useState } from 'react'
import type { ApiHealth } from './api/types'
import type { ApiClient } from './api/client'
import { BatchToolWorkspace } from './batch/BatchToolWorkspace'
import { AppHeader } from './components/AppHeader'
import { ToolSection } from './components/ToolSection'
import { ImageToolWorkspace } from './image/ImageToolWorkspace'
import type { ImageRequestClient } from './image/types'
import { OfficeToolWorkspace } from './office/OfficeToolWorkspace'
import { OcrToolWorkspace } from './ocr/OcrToolWorkspace'
import { PdfToolWorkspace } from './pdf/PdfToolWorkspace'
import type { PdfRequestClient } from './pdf/types'
import { toolById, toolsForCategory } from './tools/catalog'
import type { ToolId } from './tools/types'
import type { MultipartRequestClient } from './workflows/useSubmission'

interface AppProps {
  checkHealth?: () => Promise<ApiHealth>
  pdfClient?: PdfRequestClient
  imageClient?: ImageRequestClient
  officeClient?: MultipartRequestClient
  ocrClient?: MultipartRequestClient
  batchClient?: ApiClient
}

function App({ checkHealth, pdfClient, imageClient, officeClient, ocrClient, batchClient }: AppProps) {
  const [selectedTool, setSelectedTool] = useState<ToolId | null>(null)
  const selectedDefinition = selectedTool ? toolById(selectedTool) : null

  return (
    <div className="app-shell">
      <AppHeader checkHealth={checkHealth} />
      <main id="main-content">
        {selectedDefinition?.category === 'batch' ? (
          <BatchToolWorkspace
            toolId={selectedDefinition.id}
            onBack={() => setSelectedTool(null)}
            client={batchClient}
          />
        ) : selectedDefinition?.category === 'pdf' ? (
          <PdfToolWorkspace
            toolId={selectedDefinition.id}
            onBack={() => setSelectedTool(null)}
            client={pdfClient}
          />
        ) : selectedDefinition?.category === 'image' ? (
          <ImageToolWorkspace
            toolId={selectedDefinition.id}
            onBack={() => setSelectedTool(null)}
            client={imageClient}
          />
        ) : selectedDefinition?.category === 'office' ? (
          <OfficeToolWorkspace
            toolId={selectedDefinition.id}
            onBack={() => setSelectedTool(null)}
            client={officeClient}
          />
        ) : selectedDefinition?.category === 'ocr' ? (
          <OcrToolWorkspace
            toolId={selectedDefinition.id}
            onBack={() => setSelectedTool(null)}
            client={ocrClient}
          />
        ) : (
          <>
            <section className="intro" aria-labelledby="intro-heading">
              <p className="eyebrow">Document work, simplified</p>
              <h1 id="intro-heading">Choose the right tool for your file</h1>
              <p className="intro__copy">
                DocuForge brings focused PDF, image, Office, and OCR utilities into one clear
                workspace. Some conversion and OCR tools depend on available server engines.
              </p>
            </section>

            <div className="catalog">
              <ToolSection
                title="Batch tools"
                description="Process multiple files with tracked progress, cancellation, recovery, and one ZIP download."
                tools={toolsForCategory('batch')}
                onOpen={setSelectedTool}
              />
              <ToolSection
                title="PDF tools"
                description="Organize, refine, and transform PDF documents while keeping every operation focused."
                tools={toolsForCategory('pdf')}
                onOpen={setSelectedTool}
              />
              <ToolSection
                title="Image tools"
                description="Prepare images for sharing, storage, and document workflows."
                tools={toolsForCategory('image')}
                onOpen={setSelectedTool}
              />
              <ToolSection
                title="Office tools"
                description="Convert Word documents, presentations, and workbooks to PDF when the server rendering engine is available."
                tools={toolsForCategory('office')}
                onOpen={setSelectedTool}
              />
              <ToolSection
                title="OCR tools"
                description="Extract text from scanned images and PDFs, or make scanned PDFs searchable."
                tools={toolsForCategory('ocr')}
                onOpen={setSelectedTool}
              />
            </div>
          </>
        )}
      </main>
      <footer className="app-footer">
        <p>DocuForge MVP · Local-first document processing foundations</p>
      </footer>
    </div>
  )
}

export default App

import { useState } from 'react'
import type { ApiHealth } from './api/types'
import { AppHeader } from './components/AppHeader'
import { ToolSection } from './components/ToolSection'
import { PdfToolWorkspace } from './pdf/PdfToolWorkspace'
import type { PdfRequestClient } from './pdf/types'
import { toolsForCategory } from './tools/catalog'
import type { PdfToolId } from './tools/types'

interface AppProps {
  checkHealth?: () => Promise<ApiHealth>
  pdfClient?: PdfRequestClient
}

function App({ checkHealth, pdfClient }: AppProps) {
  const [selectedPdfTool, setSelectedPdfTool] = useState<PdfToolId | null>(null)

  return (
    <div className="app-shell">
      <AppHeader checkHealth={checkHealth} />
      <main id="main-content">
        {selectedPdfTool ? (
          <PdfToolWorkspace
            toolId={selectedPdfTool}
            onBack={() => setSelectedPdfTool(null)}
            client={pdfClient}
          />
        ) : (
          <>
            <section className="intro" aria-labelledby="intro-heading">
              <p className="eyebrow">Document work, simplified</p>
              <h1 id="intro-heading">Choose the right tool for your file</h1>
              <p className="intro__copy">
                DocuForge brings focused PDF and image utilities into one clear
                workspace. PDF workflows are ready to use; image interfaces arrive next.
              </p>
            </section>

            <div className="catalog">
              <ToolSection
                title="PDF tools"
                description="Organize, refine, and transform PDF documents while keeping every operation focused."
                tools={toolsForCategory('pdf')}
                onOpen={setSelectedPdfTool}
              />
              <ToolSection
                title="Image tools"
                description="Prepare images for sharing, storage, and document workflows."
                tools={toolsForCategory('image')}
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

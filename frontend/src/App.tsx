import { useState } from 'react'
import type { ApiHealth } from './api/types'
import { AppHeader } from './components/AppHeader'
import { ToolSection } from './components/ToolSection'
import { ImageToolWorkspace } from './image/ImageToolWorkspace'
import type { ImageRequestClient } from './image/types'
import { PdfToolWorkspace } from './pdf/PdfToolWorkspace'
import type { PdfRequestClient } from './pdf/types'
import { toolById, toolsForCategory } from './tools/catalog'
import type { ToolId } from './tools/types'

interface AppProps {
  checkHealth?: () => Promise<ApiHealth>
  pdfClient?: PdfRequestClient
  imageClient?: ImageRequestClient
}

function App({ checkHealth, pdfClient, imageClient }: AppProps) {
  const [selectedTool, setSelectedTool] = useState<ToolId | null>(null)
  const selectedDefinition = selectedTool ? toolById(selectedTool) : null

  return (
    <div className="app-shell">
      <AppHeader checkHealth={checkHealth} />
      <main id="main-content">
        {selectedDefinition?.category === 'pdf' ? (
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
        ) : (
          <>
            <section className="intro" aria-labelledby="intro-heading">
              <p className="eyebrow">Document work, simplified</p>
              <h1 id="intro-heading">Choose the right tool for your file</h1>
              <p className="intro__copy">
                DocuForge brings focused PDF and image utilities into one clear
                workspace. All current PDF and image workflows are ready to use.
              </p>
            </section>

            <div className="catalog">
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

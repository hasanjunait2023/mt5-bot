import { Outlet, useLocation } from 'react-router-dom'
import { TopBar } from './TopBar'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'

export function Layout() {
  const { pathname } = useLocation()

  return (
    <div className="relative flex flex-col h-screen text-text-primary overflow-hidden">
      {/* Ambient cinematic backdrop — depth 0/1, decorative only */}
      <div className="ambient" aria-hidden="true">
        <div className="ambient-grid" />
        <div className="ambient-blob a" />
        <div className="ambient-blob b" />
      </div>

      <div className="relative z-10 flex flex-col h-full">
        <TopBar />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main
            key={pathname}
            className="flex-1 overflow-y-auto px-3 py-4 md:px-7 md:py-7 pb-24 md:pb-7 reveal"
          >
            <div className="mx-auto w-full max-w-[1500px]">
              <Outlet />
            </div>
          </main>
        </div>
        <MobileNav />
      </div>
    </div>
  )
}

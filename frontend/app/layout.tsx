import './globals.css';import type {Metadata} from 'next';
export const metadata:Metadata={title:'OpusDrop — Upload. Share. That’s It.',description:'Private-by-design direct file links without accounts.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body><div className="min-h-screen gridbg">{children}</div></body></html>}

import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export function SecureImage({ src, alt }: { src: string; alt: string }) {
  const [objectUrl, setObjectUrl] = useState<string>()
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    let createdUrl: string | undefined
    setFailed(false)
    api
      .download(src)
      .then((blob) => {
        if (!active) return
        createdUrl = URL.createObjectURL(blob)
        setObjectUrl(createdUrl)
      })
      .catch(() => active && setFailed(true))
    return () => {
      active = false
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [src])

  if (failed) return <div className="grid aspect-[1.414/1] place-items-center bg-slate-100 text-sm text-slate-500">Prévia indisponível</div>
  if (!objectUrl) return <div className="grid aspect-[1.414/1] place-items-center bg-slate-100"><span className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-200 border-t-emerald-700" /></div>
  return <img src={objectUrl} alt={alt} className="aspect-[1.414/1] w-full object-cover object-top" />
}

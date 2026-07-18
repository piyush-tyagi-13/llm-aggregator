import { Tooltip } from './tooltip'

interface HelpNodeProps {
  content: string
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export function HelpNode({ content, side = 'right', className = '' }: HelpNodeProps) {
  return (
    <Tooltip content={content} side={side}>
      <span
        className={`inline-flex size-4 cursor-help items-center justify-center rounded-full border border-zinc-500/40 text-[10px] font-bold leading-none text-zinc-500 transition-colors hover:border-zinc-300 hover:text-zinc-300 ${className}`}
        aria-label={content}
      >
        ?
      </span>
    </Tooltip>
  )
}

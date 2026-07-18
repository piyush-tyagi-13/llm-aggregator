import * as TooltipPrimitive from '@radix-ui/react-tooltip'

const TooltipRoot = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger
const TooltipContent = TooltipPrimitive.Content

interface TooltipProps {
  content: string
  children: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
  return (
    <TooltipRoot>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent
        side={side}
        className="z-50 max-w-xs rounded-lg border border-zinc-700/50 bg-zinc-900 px-3 py-2 text-xs text-zinc-100 shadow-xl backdrop-blur-sm"
      >
        {content}
        <TooltipPrimitive.Arrow className="fill-zinc-700/50" />
      </TooltipContent>
    </TooltipRoot>
  )
}

export const TooltipProvider = TooltipPrimitive.Provider

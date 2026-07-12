import * as React from "react"
import { Popover as PopoverPrimitive } from "@base-ui-components/react/popover"

import { cn } from "@/lib/utils"

const Popover = PopoverPrimitive.Root

// Wraps Base UI's Popover.Trigger to preserve the Radix-style `asChild` API.
// Base UI uses a `render` prop for composition instead of `asChild`.
const PopoverTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Trigger> & {
    asChild?: boolean
  }
>(({ asChild, children, ...props }, ref) => {
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<Record<string, unknown>>
    return (
      <PopoverPrimitive.Trigger ref={ref} {...props} render={child} />
    )
  }
  return (
    <PopoverPrimitive.Trigger ref={ref} {...props}>
      {children}
    </PopoverPrimitive.Trigger>
  )
})
PopoverTrigger.displayName = "PopoverTrigger"

// Wraps Base UI's Popover.Close to preserve the Radix-style `asChild` API.
const PopoverClose = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Close> & {
    asChild?: boolean
  }
>(({ asChild, children, ...props }, ref) => {
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<Record<string, unknown>>
    return (
      <PopoverPrimitive.Close ref={ref} {...props} render={child} />
    )
  }
  return (
    <PopoverPrimitive.Close ref={ref} {...props}>
      {children}
    </PopoverPrimitive.Close>
  )
})
PopoverClose.displayName = "PopoverClose"

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Popup>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Popup> & {
    align?: "center" | "start" | "end"
    sideOffset?: number
  }
>(({ className, align = "center", sideOffset = 6, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Positioner align={align} sideOffset={sideOffset}>
      <PopoverPrimitive.Popup
        ref={ref}
        className={cn(
          "z-50 w-72 rounded-lg border border-white/10 bg-popover/95 p-4 text-popover-foreground shadow-lg backdrop-blur-xl outline-none data-open:animate-in data-closed:animate-out data-closed:fade-out-0 data-open:fade-in-0 data-closed:zoom-out-95 data-open:zoom-in-95",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Positioner>
  </PopoverPrimitive.Portal>
))
PopoverContent.displayName = "PopoverContent"

export { Popover, PopoverTrigger, PopoverContent, PopoverClose }

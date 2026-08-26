import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors select-none",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        ghost: "border-transparent hover:bg-accent hover:text-accent-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLElement>,
    VariantProps<typeof badgeVariants> {
  /** Render a keyboard-operable button only for genuinely interactive badges. */
  interactive?: boolean
}

function Badge({ className, variant, interactive = false, ...props }: BadgeProps) {
  const classes = cn(
    badgeVariants({ variant }),
    interactive && "cursor-pointer focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
    className
  )

  if (interactive) {
    return (
      <button
        type="button"
        className={classes}
        {...(props as React.ButtonHTMLAttributes<HTMLButtonElement>)}
      />
    )
  }

  return <span className={classes} {...props} />
}

export { Badge, badgeVariants }

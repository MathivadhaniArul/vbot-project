
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";
import { cn } from "@/lib/models/utils";
import type { UIMessage } from "ai";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, HTMLAttributes } from "react";

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: UIMessage["role"];
};

export const Message = ({
  className,
  from,
  ...props
}: MessageProps) => (
  <div
    className={cn(
      "group flex w-full gap-3 py-4",
      from === "user"
        ? "is-user justify-end"
        : "is-assistant justify-start",
      className
    )}
    {...props}
  />
);

const messageContentVariants = cva(
  "flex flex-col overflow-hidden text-sm",
  {
    variants: {
      variant: {
        contained: [
          "max-w-[90%] md:max-w-[80%]",
          "rounded-2xl px-4 py-3",

          // User bubble
          "group-[.is-user]:bg-primary",
          "group-[.is-user]:text-primary-foreground",

          // Assistant bubble
          "group-[.is-assistant]:bg-card",
          "group-[.is-assistant]:border",
          "group-[.is-assistant]:shadow-sm",
          "group-[.is-assistant]:text-foreground",
        ],

        flat: [
          "max-w-[90%] md:max-w-[80%]",

          "group-[.is-user]:rounded-2xl",
          "group-[.is-user]:bg-secondary",
          "group-[.is-user]:px-4",
          "group-[.is-user]:py-3",
          "group-[.is-user]:text-foreground",

          "group-[.is-assistant]:text-foreground",
        ],
      },
    },
    defaultVariants: {
      variant: "contained",
    },
  }
);

export type MessageContentProps =
  HTMLAttributes<HTMLDivElement> &
    VariantProps<typeof messageContentVariants>;

export const MessageContent = ({
  children,
  className,
  variant,
  ...props
}: MessageContentProps) => (
  <div
    className={cn(
      messageContentVariants({ variant }),
      // Typography support
      "prose prose-sm dark:prose-invert max-w-none",
      "prose-headings:font-semibold",
      "prose-headings:mb-2",
      "prose-headings:mt-4",
      "prose-p:my-2",
      "prose-p:leading-7",
      "prose-ul:my-2",
      "prose-li:my-1",
      "prose-strong:text-foreground",
      "prose-a:text-primary",
      "prose-a:no-underline hover:prose-a:underline",
      className
    )}
    {...props}
  >
    {children}
  </div>
);

export type MessageAvatarProps =
  ComponentProps<typeof Avatar> & {
    src: string;
    name?: string;
  };

export const MessageAvatar = ({
  src,
  name,
  className,
  ...props
}: MessageAvatarProps) => (
  <Avatar
    className={cn(
      "size-8 shrink-0 ring-1 ring-border",
      className
    )}
    {...props}
  >
    <AvatarImage
      alt=""
      className="mt-0 mb-0"
      src={src}
    />
    <AvatarFallback>
      {name?.slice(0, 2).toUpperCase() || "AI"}
    </AvatarFallback>
  </Avatar>
);
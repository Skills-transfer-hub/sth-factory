import type { ClientModule } from 'claude-code'

import ok from './frames/ok'
import work from './frames/work'
import done from './frames/done'
import error from './frames/error'
import update from './frames/update'
import noConfig from './frames/noConfig'

const frames = { ok, work, done, error, update, noConfig }
type BuddyProps = { state: keyof typeof frames; caption: string }

// One local clock, one HD pose at a time. The pane only sends state and caption.
const Buddy: ClientModule<BuddyProps, number> = (props, surface) => {
  if (surface.state === undefined) {
    surface.setState(0)
    surface.every(50, () => surface.setState((surface.state ?? 0) + 1))
  }
  const poses = frames[props.state]
  const pose = poses[(surface.state ?? 0) % poses.length]!
  return {
    type: 'Svg',
    props: {
      source: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 384" width="144" height="144">' +
        `<image href="data:image/webp;base64,${pose}" width="384" height="384"/></svg>`,
      alt: props.caption,
      width: 144,
      height: 144,
      isInteractive: false,
    },
  }
}

export default Buddy

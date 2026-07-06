// react-plotly.js wired to the prebuilt dist so Vite serves it without trying to
// bundle Plotly's source (which is large and CJS-flavoured).
import createPlotlyComponent from 'react-plotly.js/factory'
// @ts-expect-error the dist-min build ships no types
import Plotly from 'plotly.js-dist-min'

const Plot = createPlotlyComponent(Plotly)
export default Plot

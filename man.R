## Get DNA sequences from UCSC Genome Browser
## Genome: Mouse mm10
## Author: Jada Roth
## August 16 2024

## Connect to UCSC genome browser
connectDNA = function(chrom, start, end) {
  url <- paste0("https://api.genome.ucsc.edu/getData/sequence?genome=mm10;chrom=", chrom, ";start=", start, ";end=", end)
  response <- GET(url)
  
  if (status_code(response) == 200) {
    content <- content(response, "text")
    data <- fromJSON(content)
    return(toupper(data$dna))
  } 
  else {
    return(NA)
  }
}

## Iterate through data frame, "data". Data should have 1 column, titled "Coordinates" containing chr:START-END
getDNA = function(data){
  data$'DNA Sequence' <- NA

  print("Getting DNA")
  x = nrow(data)
  for(i in 1:x){
    try({
      coords = strsplit(data$Coordinates[i], "[:-]")[[1]]
      chrom = coords[1]
      start = as.numeric(coords[2])
      end = as.numeric(coords[3])

      sequence = connectDNA(chrom, start, end)
      data$'DNA Sequence'[i] = sequence},
        silent = TRUE)
    }
  return(data)
  }

## Write to excel file
write_xlsx(data, "sequences.xlsx")

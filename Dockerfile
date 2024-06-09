FROM public.ecr.aws/lambda/python
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
ADD subawoo.py ./
CMD ["subawoo.handler"]

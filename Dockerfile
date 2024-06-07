FROM public.ecr.aws/lambda/python
RUN dnf install -y awscli
RUN pip3 install subarulink
ADD subawoo.py ./
CMD ["subawoo.handler"]

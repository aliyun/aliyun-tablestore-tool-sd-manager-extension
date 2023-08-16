> README available in: [English](README.md) | [中文](README-zh.md)

# Introduction

**Tablestore-sd-manager** is an extension for [AUTOMATIC1111's Stable Diffusion Web UI](https://github.com/AUTOMATIC1111/stable-diffusion-webui).**

It allows to store prompt, parameters to tablestore, then you can search it by [Tablestore](https://www.aliyun.com/product/ots/).

You can use the serverless `sd-web-ui` hosted on the cloud to build `sd-web-ui` service and generate images more conveniently. [Source code link.](https://github.com/devsapp/fc-stable-diffuson)

# Usage

## 1. Set system environment

Set system environment variables if needed before starting the app:

| Variable                    | Example                                                  |
|-----------------------------|----------------------------------------------------------|
| `OTS_ENDPOINT_ENV`          | `https://demo-instance-name.cn-qingdao.ots.aliyuncs.com` |
| `OTS_ACCESS_KEY_ID_ENV`     | `access_key_id_xxxxx`                                    |
| `OTS_ACCESS_KEY_SECRET_ENV` | `access_key_secret_xxxxx`                                |
| `OTS_INSTANCE_NAME_ENV`     | `demo-instance-name`                                     |

##### Example

The following only lists the Linux environment variable modifications.

You can temporarily run the following `export` commands directly before starting the `web-ui` script in the terminal.

If you want it to take effect permanently, it is recommended to add the following code to your terminal configuration file, such as `.bashrc`

```bash
export OTS_ENDPOINT_ENV=https://demo-instance-name.cn-qingdao.ots.aliyuncs.com
export OTS_ACCESS_KEY_ID_ENV=access_key_id_xxxxx
export OTS_ACCESS_KEY_SECRET_ENV=access_key_secret_xxxxx
export OTS_INSTANCE_NAME_ENV=demo-instance-name
```

## 2. Use it in sd-web-ui

1. Click on the relevant tab.
    - ![Click on the relevant tab](assets/home.jpg)
2. View overview.
    - ![View overview](assets/overview.jpg)
3. Manage and query historically generated images.
    1. Before query.
        - ![before_search](assets/before_search.jpg)
    2. After query, you can browse pictures through the gallery component.
        - ![after_search](assets/after_search.jpg)
    3. Click on a picture in the gallery to enlarge it, and you can view the detailed information of the picture.
        - Press the 'Esc' button on your keyboard or click the "x" in the upper right corner of the image to return to list mode.
        - ![big_image](assets/big_image.jpg)